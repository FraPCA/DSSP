from dssp import DSSPTestable
import gc

gc.disable()

#def test_DSSPTestable_1():
 #   result = DSSPTestable(5, [2,3,2,3,2], 5, 21)
 #   assert result == 0

def test_benchmark_DSSPTestable_1(benchmark):
    benchmark(DSSPTestable, 5, [2,3,2,3,2], 5, 21, [[1, 2], [2, 3], [3, 4], [1, 4], [4, 5]])

# run benchmark
gc.enable()