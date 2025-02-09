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

from sdc.tests.test_base import TestCase

import pandas as pd
import numpy as np
import numba as nb
from numba import types

from sdc.types import (
    SeriesType,
    CategoricalDtypeType,
    Categorical,
)
from sdc.datatypes.indexes.positional_index_type import PositionalIndexType


class SeriesCategoryTest(TestCase):
    """
    Test for pandas Series with CategoricalDtype.
    """

    def _pd_value(self):
        return pd.Series(data=[1, 2, 3, 2, 1], dtype='category')

    def test_typeof(self):
        pd_value = self._pd_value()
        nb_type = nb.typeof(pd_value)

        assert(isinstance(nb_type, SeriesType))
        assert(nb_type.dtype == CategoricalDtypeType(categories=[1, 2, 3], ordered=False))
        assert(nb_type.index == PositionalIndexType(False))
        assert(nb_type.data == Categorical(CategoricalDtypeType(categories=[1, 2, 3], ordered=False)))

    def test_unboxing(self):
        @nb.njit
        def func(c):
            pass

        pd_value = self._pd_value()
        func(pd_value)

    def test_boxing(self):
        @nb.njit
        def func(c):
            return c

        pd_value = self._pd_value()
        boxed = func(pd_value)
        assert(boxed.equals(pd_value))

    def test_lowering(self):
        pd_value = self._pd_value()

        @nb.njit
        def func():
            return pd_value

        boxed = func()
        assert(boxed.equals(pd_value))

    def test_constructor(self):
        @nb.njit
        def func():
            return pd.Series(data=(1, 2, 3, 2, 1), dtype='category')

        boxed = func()
        assert(boxed.equals(self._pd_value()))

    def test_constructor_list(self):
        @nb.njit
        def func():
            return pd.Series(data=[1, 2, 3, 2, 1], dtype='category')

        boxed = func()
        assert(boxed.equals(self._pd_value()))

    def test_constructor_CategoricalDtype(self):
        @nb.njit
        def func():
            return pd.Series(data=(1, 2, 3, 2, 1), dtype=pd.CategoricalDtype(categories=(1, 2, 3)))

        boxed = func()
        assert(boxed.equals(self._pd_value()))

    def test_constructor_CategoricalDtype_list(self):
        @nb.njit
        def func():
            return pd.Series(data=[1, 2, 3, 2, 1], dtype=pd.CategoricalDtype(categories=[1, 2, 3]))

        boxed = func()
        assert(boxed.equals(self._pd_value()))
