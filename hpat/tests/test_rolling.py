import unittest
import pandas as pd
import numpy as np
import pyarrow.parquet as pq
import numba
import hpat
from hpat.tests.test_utils import (count_array_REPs, count_parfor_REPs,
    count_parfor_OneDs, count_array_OneDs, dist_IR_contains)


class TestRolling(unittest.TestCase):
    def test_fixed1(self):
        def test_impl(df):
            return df.rolling(2).sum()

        hpat_func = hpat.jit(test_impl)
        df = pd.DataFrame({'B': [0, 1, 2, np.nan, 4]})
        pd.testing.assert_frame_equal(hpat_func(df), test_impl(df))

    def test_fixed2(self):
        def test_impl(df):
            return df.rolling(2).sum()

        hpat_func = hpat.jit(test_impl)
        df = pd.DataFrame({'B': [0, 1, 2, -2, 4]})
        pd.testing.assert_frame_equal(hpat_func(df), test_impl(df))

    def test_fixed_center1(self):
        def test_impl(df):
            return df.rolling(5, center=True).sum()

        hpat_func = hpat.jit(test_impl)
        n = 111
        df = pd.DataFrame({'B': np.arange(n)})
        pd.testing.assert_frame_equal(hpat_func(df), test_impl(df))

    def test_fixed_center2(self):
        def test_impl(df):
            return df.rolling(5, center=False).sum()

        hpat_func = hpat.jit(test_impl)
        n = 111
        df = pd.DataFrame({'B': np.arange(n)})
        pd.testing.assert_frame_equal(hpat_func(df), test_impl(df))

if __name__ == "__main__":
    unittest.main()
