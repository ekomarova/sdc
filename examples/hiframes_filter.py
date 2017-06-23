import pandas as pd
import numpy as np
import hpat

@hpat.jit
def filter_df(n):
    df = pd.DataFrame({'A': np.random.ranf(10),'B': np.random.ranf(10)})
    df1 = df[df.A>.5]
    return np.sum(df1.B)

n = 10
print(filter_df(n))
