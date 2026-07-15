import pandas as pd

df = pd.read_csv("../datasets/properties_synthetic_v1.csv")

df.head(23).to_csv("testbench.csv")