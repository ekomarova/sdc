# *****************************************************************************
# Copyright (c) 2020, Intel Corporation All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
#     Redistributions of source code must retain the above copyright notice,
#     this list of conditions and the following disclaimer.
#
#     Redistributions in binary form must reproduce the above copyright notice,
#     this list of conditions and the following disclaimer in the documentation
#     and/or other materials provided with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO,
# THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR
# PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR
# CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL,
# EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO,
# PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS;
# OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY,
# WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR
# OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE,
# EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
# *****************************************************************************

"""

| This file contains SDC overloads for common algorithms used internally

"""

import numpy
import pandas
from pandas.core.indexing import IndexingError

import numba
from numba.misc import quicksort
from numba import types
from numba.core.errors import TypingError
from numba.extending import register_jitable
from numba.np import numpy_support
from numba.typed import Dict
from numba.typed.typedobjectutils import _nonoptional

import sdc
from sdc.datatypes.indexes import *
from sdc.hiframes.api import isna
from sdc.hiframes.pd_series_type import SeriesType
from sdc.functions import numpy_like
from sdc.str_arr_type import string_array_type, StringArrayType
from sdc.str_arr_ext import (num_total_chars, append_string_array_to,
                             str_arr_is_na, pre_alloc_string_array, str_arr_set_na, string_array_type,
                             cp_str_list_to_array, create_str_arr_from_list, get_utf8_size,
                             str_arr_set_na_by_mask, str_arr_stable_argosort)
from sdc.utilities.prange_utils import parallel_chunks
from sdc.utilities.utils import sdc_overload, sdc_register_jitable
from sdc.utilities.sdc_typing_utils import (
                            find_common_dtype_from_numpy_dtypes,
                            TypeChecker,
                            sdc_pandas_index_types,
                            sdc_pandas_df_column_types,
                            sdc_old_index_types,
                            )


def hpat_arrays_append(A, B):
    pass


@sdc_overload(hpat_arrays_append, jit_options={'parallel': False})
def hpat_arrays_append_overload(A, B):
    """Function for appending underlying arrays (A and B) or list/tuple of arrays B to an array A"""

    if not isinstance(A, sdc_pandas_df_column_types):
        return None

    # this function should work with arrays, not indexes, but until all indexes support
    # common API (e.g. append is not supported for types.Array indexes) it is simplier to support
    # indexes here rather than branch depending on index types on call site
    # TO-DO: clean-up when Float64Index and StringArrayIndex are supported
    # if not (isinstance(B, sdc_pandas_df_column_types) or isinstance(B.dtype, sdc_pandas_df_column_types)):
    #     return None
    valid_num_single_B_dtype = (types.Array, ) + sdc_pandas_index_types
    valid_num_seq_B_dtypes = (types.Array, ) + sdc_pandas_index_types

    if isinstance(A, types.Array):
        if isinstance(B, valid_num_single_B_dtype):
            convert_B = not isinstance(B, types.Array)
            def _append_single_numeric_impl(A, B):
                _B = B if convert_B == False else B.values  # noqa
                return numpy.concatenate((A, _B,))

            return _append_single_numeric_impl

        elif (isinstance(B, (types.UniTuple, types.List)) and isinstance(B.dtype, valid_num_seq_B_dtypes)):
            numba_common_dtype = find_common_dtype_from_numpy_dtypes([A.dtype, B.dtype.dtype], [])

            convert_B = not isinstance(B.dtype, types.Array)
            # TODO: refactor to use numpy.concatenate when Numba supports building a tuple at runtime
            def _append_list_numeric_impl(A, B):

                total_length = len(A) + numpy.array([len(arr) for arr in B]).sum()
                new_data = numpy.empty(total_length, numba_common_dtype)

                stop = len(A)
                new_data[:stop] = A
                for arr in B:
                    start = stop
                    stop = start + len(arr)
                    if convert_B == False:   # noqa
                        new_data[start:stop] = arr
                    else:
                        new_data[start:stop] = arr.values
                return new_data

            return _append_list_numeric_impl

    elif A == string_array_type:
        if B == string_array_type:
            def _append_single_string_array_impl(A, B):
                total_size = len(A) + len(B)
                total_chars = num_total_chars(A) + num_total_chars(B)
                new_data = sdc.str_arr_ext.pre_alloc_string_array(total_size, total_chars)

                pos = 0
                pos += append_string_array_to(new_data, pos, A)
                pos += append_string_array_to(new_data, pos, B)

                return new_data

            return _append_single_string_array_impl
        elif (isinstance(B, (types.UniTuple, types.List)) and B.dtype == string_array_type):
            def _append_list_string_array_impl(A, B):
                array_list = [A] + list(B)
                total_size = numpy.array([len(arr) for arr in array_list]).sum()
                total_chars = numpy.array([num_total_chars(arr) for arr in array_list]).sum()

                new_data = sdc.str_arr_ext.pre_alloc_string_array(total_size, total_chars)

                pos = 0
                pos += append_string_array_to(new_data, pos, A)
                for arr in B:
                    pos += append_string_array_to(new_data, pos, arr)

                return new_data

            return _append_list_string_array_impl


@sdc_register_jitable
def fill_array(data, size, fill_value=numpy.nan, push_back=True):
    """
    Fill array with given values to reach the size
    """

    if push_back:
        return numpy.append(data, numpy.repeat(fill_value, size - data.size))

    return numpy.append(numpy.repeat(fill_value, size - data.size), data)


@sdc_register_jitable
def fill_str_array(data, size, push_back=True):
    """
    Fill StringArrayType array with given values to reach the size
    """

    string_array_size = len(data)
    nan_array_size = size - string_array_size
    num_chars = sdc.str_arr_ext.num_total_chars(data)

    result_data = sdc.str_arr_ext.pre_alloc_string_array(size, num_chars)

    # Keep NaN values of initial array
    arr_is_na_mask = numpy.array([sdc.hiframes.api.isna(data, i) for i in range(string_array_size)])
    data_str_list = sdc.str_arr_ext.to_string_list(data)
    nan_list = [''] * nan_array_size

    result_list = data_str_list + nan_list if push_back else nan_list + data_str_list
    cp_str_list_to_array(result_data, result_list)

    # Batch=64 iteration to avoid threads competition
    batch_size = 64
    if push_back:
        for i in numba.prange(size//batch_size + 1):
            for j in range(i*batch_size, min((i+1)*batch_size, size)):
                if j < string_array_size:
                    if arr_is_na_mask[j]:
                        str_arr_set_na(result_data, j)
                else:
                    str_arr_set_na(result_data, j)

    else:
        for i in numba.prange(size//batch_size + 1):
            for j in range(i*batch_size, min((i+1)*batch_size, size)):
                if j < nan_array_size:
                    str_arr_set_na(result_data, j)
                else:
                    str_arr_j = j - nan_array_size
                    if arr_is_na_mask[str_arr_j]:
                        str_arr_set_na(result_data, j)

    return result_data


@numba.njit
def _hpat_ensure_array_capacity(new_size, arr):
    """ Function ensuring that the size of numpy array is at least as specified
        Returns newly allocated array of bigger size with copied elements if existing size is less than requested
    """

    k = len(arr)
    if k >= new_size:
        return arr

    n = k
    while n < new_size:
        n = 2 * n
    res = numpy.empty(n, arr.dtype)
    res[:k] = arr[:k]
    return res


def _sdc_internal_join(left, right):
    pass


@sdc_overload(_sdc_internal_join, jit_options={'parallel': False})
def _sdc_internal_join_ovld(left, right):

    if isinstance(left, types.Array) and isinstance(right, types.Array):

        numba_common_dtype = find_common_dtype_from_numpy_dtypes([left.dtype, right.dtype], [])
        if isinstance(numba_common_dtype, types.Number):

            def sdc_join_series_indexes_impl(left, right):

                # allocate result arrays
                lsize = len(left)
                rsize = len(right)
                est_total_size = int(1.1 * (lsize + rsize))

                lidx = numpy.empty(est_total_size, numpy.int64)
                ridx = numpy.empty(est_total_size, numpy.int64)
                joined = numpy.empty(est_total_size, numba_common_dtype)

                left_nan = []
                right_nan = []
                for i in range(lsize):
                    if numpy.isnan(left[i]):
                        left_nan.append(i)
                for i in range(rsize):
                    if numpy.isnan(right[i]):
                        right_nan.append(i)

                # sort arrays saving the old positions
                sorted_left = numpy_like.argsort(left, kind='mergesort')
                sorted_right = numpy_like.argsort(right, kind='mergesort')
                # put the position of the nans in an increasing sequence
                sorted_left[lsize-len(left_nan):] = left_nan
                sorted_right[rsize-len(right_nan):] = right_nan

                i, j, k = 0, 0, 0
                while (i < lsize and j < rsize):
                    joined = _hpat_ensure_array_capacity(k + 1, joined)
                    lidx = _hpat_ensure_array_capacity(k + 1, lidx)
                    ridx = _hpat_ensure_array_capacity(k + 1, ridx)

                    left_index = left[sorted_left[i]]
                    right_index = right[sorted_right[j]]

                    if (left_index < right_index) or numpy.isnan(right_index):
                        joined[k] = left_index
                        lidx[k] = sorted_left[i]
                        ridx[k] = -1
                        i += 1
                        k += 1
                    elif (left_index > right_index) or numpy.isnan(left_index):
                        joined[k] = right_index
                        lidx[k] = -1
                        ridx[k] = sorted_right[j]
                        j += 1
                        k += 1
                    else:
                        # find ends of sequences of equal index values in left and right
                        ni, nj = i, j
                        while (ni < lsize and left[sorted_left[ni]] == left_index):
                            ni += 1
                        while (nj < rsize and right[sorted_right[nj]] == right_index):
                            nj += 1

                        # join the blocks found into results
                        for s in numpy.arange(i, ni, 1):
                            block_size = nj - j
                            to_joined = numpy.repeat(left_index, block_size)
                            to_lidx = numpy.repeat(sorted_left[s], block_size)
                            to_ridx = numpy.array([sorted_right[k] for k in numpy.arange(j, nj, 1)], numpy.int64)

                            joined = _hpat_ensure_array_capacity(k + block_size, joined)
                            lidx = _hpat_ensure_array_capacity(k + block_size, lidx)
                            ridx = _hpat_ensure_array_capacity(k + block_size, ridx)

                            joined[k:k + block_size] = to_joined
                            lidx[k:k + block_size] = to_lidx
                            ridx[k:k + block_size] = to_ridx
                            k += block_size
                        i = ni
                        j = nj

                # fill the end of joined with remaining part of left or right
                if i < lsize:
                    block_size = lsize - i
                    joined = _hpat_ensure_array_capacity(k + block_size, joined)
                    lidx = _hpat_ensure_array_capacity(k + block_size, lidx)
                    ridx = _hpat_ensure_array_capacity(k + block_size, ridx)
                    ridx[k: k + block_size] = numpy.repeat(-1, block_size)
                    while i < lsize:
                        joined[k] = left[sorted_left[i]]
                        lidx[k] = sorted_left[i]
                        i += 1
                        k += 1

                elif j < rsize:
                    block_size = rsize - j
                    joined = _hpat_ensure_array_capacity(k + block_size, joined)
                    lidx = _hpat_ensure_array_capacity(k + block_size, lidx)
                    ridx = _hpat_ensure_array_capacity(k + block_size, ridx)
                    lidx[k: k + block_size] = numpy.repeat(-1, block_size)
                    while j < rsize:
                        joined[k] = right[sorted_right[j]]
                        ridx[k] = sorted_right[j]
                        j += 1
                        k += 1

                return joined[:k], lidx[:k], ridx[:k]

            return sdc_join_series_indexes_impl

        else:
            return None

    elif (left == string_array_type and right == string_array_type):

        def sdc_join_series_indexes_impl(left, right):

            # allocate result arrays
            lsize = len(left)
            rsize = len(right)
            est_total_size = int(1.1 * (lsize + rsize))

            lidx = numpy.empty(est_total_size, numpy.int64)
            ridx = numpy.empty(est_total_size, numpy.int64)

            # use Series.sort_values since argsort for StringArrays not implemented
            original_left_series = pandas.Series(left)
            original_right_series = pandas.Series(right)

            # sort arrays saving the old positions
            left_series = original_left_series.sort_values(kind='mergesort')
            right_series = original_right_series.sort_values(kind='mergesort')
            sorted_left = left_series._index
            sorted_right = right_series._index

            i, j, k = 0, 0, 0
            while (i < lsize and j < rsize):
                lidx = _hpat_ensure_array_capacity(k + 1, lidx)
                ridx = _hpat_ensure_array_capacity(k + 1, ridx)

                left_index = left[sorted_left[i]]
                right_index = right[sorted_right[j]]

                if (left_index < right_index):
                    lidx[k] = sorted_left[i]
                    ridx[k] = -1
                    i += 1
                    k += 1
                elif (left_index > right_index):
                    lidx[k] = -1
                    ridx[k] = sorted_right[j]
                    j += 1
                    k += 1
                else:
                    # find ends of sequences of equal index values in left and right
                    ni, nj = i, j
                    while (ni < lsize and left[sorted_left[ni]] == left_index):
                        ni += 1
                    while (nj < rsize and right[sorted_right[nj]] == right_index):
                        nj += 1

                    # join the blocks found into results
                    for s in numpy.arange(i, ni, 1):
                        block_size = nj - j
                        to_lidx = numpy.repeat(sorted_left[s], block_size)
                        to_ridx = numpy.array([sorted_right[k] for k in numpy.arange(j, nj, 1)], numpy.int64)

                        lidx = _hpat_ensure_array_capacity(k + block_size, lidx)
                        ridx = _hpat_ensure_array_capacity(k + block_size, ridx)

                        lidx[k:k + block_size] = to_lidx
                        ridx[k:k + block_size] = to_ridx
                        k += block_size
                    i = ni
                    j = nj

            # fill the end of joined with remaining part of left or right
            if i < lsize:
                block_size = lsize - i
                lidx = _hpat_ensure_array_capacity(k + block_size, lidx)
                ridx = _hpat_ensure_array_capacity(k + block_size, ridx)
                ridx[k: k + block_size] = numpy.repeat(-1, block_size)
                while i < lsize:
                    lidx[k] = sorted_left[i]
                    i += 1
                    k += 1

            elif j < rsize:
                block_size = rsize - j
                lidx = _hpat_ensure_array_capacity(k + block_size, lidx)
                ridx = _hpat_ensure_array_capacity(k + block_size, ridx)
                lidx[k: k + block_size] = numpy.repeat(-1, block_size)
                while j < rsize:
                    ridx[k] = sorted_right[j]
                    j += 1
                    k += 1

            # count total number of characters and allocate joined array
            total_joined_size = k
            num_chars_in_joined = 0
            for i in numpy.arange(total_joined_size):
                if lidx[i] != -1:
                    num_chars_in_joined += len(left[lidx[i]])
                elif ridx[i] != -1:
                    num_chars_in_joined += len(right[ridx[i]])

            joined = pre_alloc_string_array(total_joined_size, num_chars_in_joined)

            # iterate over joined and fill it with indexes using lidx and ridx indexers
            for i in numpy.arange(total_joined_size):
                if lidx[i] != -1:
                    joined[i] = left[lidx[i]]
                    if (str_arr_is_na(left, lidx[i])):
                        str_arr_set_na(joined, i)
                elif ridx[i] != -1:
                    joined[i] = right[ridx[i]]
                    if (str_arr_is_na(right, ridx[i])):
                        str_arr_set_na(joined, i)
                else:
                    str_arr_set_na(joined, i)

            return joined, lidx, ridx

        return sdc_join_series_indexes_impl

    return None


@numba.njit
def _sdc_pandas_format_percentiles(arr):
    """ Function converting float array of percentiles to a list of strings formatted
        the same as in pandas.io.formats.format.format_percentiles
    """

    percentiles_strs = []
    for percentile in arr:
        p_as_string = str(percentile * 100)

        trim_index = len(p_as_string) - 1
        while trim_index >= 0:
            if p_as_string[trim_index] == '0':
                trim_index -= 1
                continue
            elif p_as_string[trim_index] == '.':
                break

            trim_index += 1
            break

        if trim_index < 0:
            p_as_string_trimmed = '0'
        else:
            p_as_string_trimmed = p_as_string[:trim_index]

        percentiles_strs.append(p_as_string_trimmed + '%')

    return percentiles_strs


def sdc_arrays_argsort(A, kind='quicksort'):
    pass


@sdc_overload(sdc_arrays_argsort, jit_options={'parallel': False})
def sdc_arrays_argsort_overload(A, kind='quicksort', ascending=True):
    """Function providing pandas argsort implementation for different 1D array types"""

    # kind is not known at compile time, so get this function here and use in impl if needed
    quicksort_func = quicksort.make_jit_quicksort().run_quicksort

    kind_is_default = isinstance(kind, str)
    if isinstance(A, types.Array):
        def _sdc_arrays_argsort_array_impl(A, kind='quicksort', ascending=True):
            _kind = 'quicksort' if kind_is_default == True else kind  # noqa
            return numpy_like.argsort(A, kind=_kind, ascending=ascending)

        return _sdc_arrays_argsort_array_impl

    elif A == string_array_type:
        def _sdc_arrays_argsort_str_arr_impl(A, kind='quicksort', ascending=True):

            if kind == 'quicksort':
                indexes = numpy.arange(len(A))
                data_index_pairs = list(zip(list(A), list(indexes)))
                zipped = quicksort_func(data_index_pairs)
                argsorted = [zipped[i][1] for i in indexes]
                res = numpy.array(argsorted, dtype=numpy.int64)
                # for non-stable sort the order within groups does not matter
                # so just reverse the result when sorting in descending order
                if not ascending:
                    res = res[::-1]
            elif kind == 'mergesort':
                res = str_arr_stable_argosort(A, ascending=ascending)
            else:
                raise ValueError("Unrecognized kind of sort in sdc_arrays_argsort")

            return res

        return _sdc_arrays_argsort_str_arr_impl

    elif isinstance(A, types.List):
        return None

    return None


def _sdc_pandas_series_check_axis(axis):
    pass


@sdc_overload(_sdc_pandas_series_check_axis, jit_options={'parallel': False})
def _sdc_pandas_series_check_axis_overload(axis):
    if isinstance(axis, types.UnicodeType):
        def _sdc_pandas_series_check_axis_impl(axis):
            if axis != 'index':
                raise ValueError("Method sort_values(). Unsupported parameter. Given axis != 'index'")
        return _sdc_pandas_series_check_axis_impl

    elif isinstance(axis, types.Integer):
        def _sdc_pandas_series_check_axis_impl(axis):
            if axis != 0:
                raise ValueError("Method sort_values(). Unsupported parameter. Given axis != 0")
        return _sdc_pandas_series_check_axis_impl

    return None


def _sdc_asarray(data):
    pass


@sdc_overload(_sdc_asarray)
def _sdc_asarray_overload(data):

    # TODO: extend with other types
    if not isinstance(data, types.List):
        return None

    if isinstance(data.dtype, types.UnicodeType):
        def _sdc_asarray_impl(data):
            return create_str_arr_from_list(data)

        return _sdc_asarray_impl

    else:
        result_dtype = data.dtype

        def _sdc_asarray_impl(data):
            # TODO: check if elementwise copy is needed at all
            res_size = len(data)
            res_arr = numpy.empty(res_size, dtype=result_dtype)
            for i in numba.prange(res_size):
                res_arr[i] = data[i]
            return res_arr

        return _sdc_asarray_impl

    return None


def _almost_equal(x, y):
    """Check if floats are almost equal based on the float epsilon"""
    pass


@sdc_overload(_almost_equal)
def _almost_equal_overload(x, y):
    ty_checker = TypeChecker('Function sdc.common_functions._almost_equal_overload().')
    ty_checker.check(x, types.Float)
    ty_checker.check(x, types.Float)

    common_dtype = numpy.find_common_type([], [x.name, y.name])

    def _almost_equal_impl(x, y):
        return abs(x - y) <= numpy.finfo(common_dtype).eps

    return _almost_equal_impl


def sdc_reindex_series(arr, index, name, by_index):
    pass


# TO-DO: support Series.reindex() that should replace this function
@sdc_overload(sdc_reindex_series)
def sdc_reindex_series_overload(arr, index, name, by_index):
    """ Reindexes series data by new index following the logic of pandas.core.indexing.check_bool_indexer """

    range_indexes = (isinstance(index, (PositionalIndexType, RangeIndexType))
                     and isinstance(by_index, (PositionalIndexType, RangeIndexType)))
    data_dtype, index_dtype = arr.dtype, index.dtype
    data_is_str_arr = isinstance(arr.dtype, types.UnicodeType)

    # use old implementation if old indexes types are used
    if (isinstance(index, sdc_old_index_types) or isinstance(by_index, sdc_old_index_types)):

        def sdc_reindex_series_old_impl(arr, index, name, by_index):

            # no reindexing is needed if indexes are equal, but only check if it's fast
            if range_indexes == True:  # noqa
                equal_indexes = index.equals(by_index)
            else:
                equal_indexes = False
            if (index is by_index or equal_indexes):
                return pandas.Series(data=arr, index=by_index, name=name)

            if data_is_str_arr == True:  # noqa
                _res_data = [''] * len(by_index)
                res_data_nan_mask = numpy.zeros(len(by_index), dtype=types.bool_)
            else:
                _res_data = numpy.empty(len(by_index), dtype=data_dtype)

            # build a dict of self.index values to their positions:
            map_index_to_position = Dict.empty(
                key_type=index_dtype,
                value_type=types.int32
            )

            for i, value in enumerate(index):
                if value in map_index_to_position:
                    raise ValueError("cannot reindex from a duplicate axis")
                else:
                    map_index_to_position[value] = i

            index_mismatch = 0
            for i in numba.prange(len(by_index)):
                val = by_index[i]
                if val in map_index_to_position:
                    pos_in_self = map_index_to_position[val]
                    _res_data[i] = arr[pos_in_self]
                    if data_is_str_arr == True:  # noqa
                        res_data_nan_mask[i] = isna(arr, i)
                else:
                    index_mismatch += 1
            if index_mismatch:
                msg = "Unalignable boolean Series provided as indexer " + \
                      "(index of the boolean Series and of the indexed object do not match)."
                raise IndexingError(msg)

            if data_is_str_arr == True:  # noqa
                res_data = create_str_arr_from_list(_res_data)
                str_arr_set_na_by_mask(res_data, res_data_nan_mask)
            else:
                res_data = _res_data

            return pandas.Series(data=res_data, index=by_index, name=name)

        return sdc_reindex_series_old_impl

    def sdc_reindex_series_impl(arr, index, name, by_index):

        _, new_order = index.reindex(by_index)
        if new_order is not None:
            new_order_as_array = _nonoptional(new_order)
            index_mismatch = 0
            for i in numba.prange(len(by_index)):
                if new_order_as_array[i] == -1:
                    index_mismatch += 1

            if index_mismatch:
                # TO-DO: seems it covers only specific series reindex case, generalize?
                msg = "Unalignable boolean Series provided as indexer " + \
                      "(index of the boolean Series and of the indexed object do not match)."
                raise IndexingError(msg)

            res_data = numpy_like.take(arr, new_order_as_array)
        else:
            res_data = arr

        return pandas.Series(data=res_data, index=by_index, name=name)

    return sdc_reindex_series_impl
