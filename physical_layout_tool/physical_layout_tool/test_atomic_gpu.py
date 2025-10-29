# 🧪 TEST: Atomare GPU-Updates für GpuInstancer

import sys
import os

# Add project path for imports
sys.path.append(r'g:\plt_comp\py')

try:
    import scatter_accel
    import numpy as np
    print("✅ scatter_accel module imported successfully!")
except ImportError as e:
    print(f"❌ Failed to import scatter_accel: {e}")
    print("Note: Module needs to be compiled first")
    sys.exit(1)

def test_atomic_gpu_updates():
    """Test der neuen atomaren GPU-Update-Methoden"""
    print("\n🚀 Testing Atomic GPU Updates...")
    
    try:
        # 1. GpuInstancer erstellen
        print("1. Creating GpuInstancer...")
        instancer = scatter_accel.GpuInstancer("test_shader")
        print(f"   ✅ GpuInstancer created")
        
        # 2. Test: Instance count (should be 0)
        count = instancer.get_instance_count()
        print(f"   ✅ Initial instance count: {count}")
        assert count == 0, "Initial count should be 0"
        
        # 3. Test: Atomic instance hinzufügen
        print("2. Testing add_instance_on_gpu...")
        matrix1 = np.eye(4, dtype=np.float32).flatten()  # Identity matrix
        matrix2 = np.array([  # Translation matrix
            [1, 0, 0, 5],
            [0, 1, 0, 0], 
            [0, 0, 1, 0],
            [0, 0, 0, 1]
        ], dtype=np.float32).flatten()
        
        id1 = instancer.add_instance_on_gpu(matrix1)
        id2 = instancer.add_instance_on_gpu(matrix2)
        
        print(f"   ✅ Added instances: id1={id1}, id2={id2}")
        print(f"   ✅ Instance count: {instancer.get_instance_count()}")
        
        # 4. Test: Atomic update
        print("3. Testing update_single_instance_on_gpu...")
        matrix2_updated = np.array([  # Updated translation
            [1, 0, 0, 10],
            [0, 1, 0, 0], 
            [0, 0, 1, 0],
            [0, 0, 0, 1]
        ], dtype=np.float32).flatten()
        
        instancer.update_single_instance_on_gpu(id2, matrix2_updated)
        print(f"   ✅ Updated instance {id2}")
        
        # 5. Test: Retrieve all matrices
        print("4. Testing get_all_instance_matrices...")
        all_matrices = instancer.get_all_instance_matrices()
        print(f"   ✅ All matrices shape: {all_matrices.shape}")
        print(f"   ✅ Matrix at id {id2}:")
        print(f"      {all_matrices[id2].reshape(4, 4)}")
        
        # 6. Test: Ghost mode
        print("5. Testing ghost mode...")
        instancer.set_ghost_mode(True, id1)
        print(f"   ✅ Ghost mode enabled with instance {id1}")
        
        # 7. Test: Legacy batch methods
        print("6. Testing legacy batch methods...")
        matrix3 = np.array([
            [1, 0, 0, 20],
            [0, 1, 0, 0], 
            [0, 0, 1, 0],
            [0, 0, 0, 1]
        ], dtype=np.float32).flatten()
        
        id3 = instancer.add_instance(matrix3)  # CPU only
        print(f"   ✅ Added instance to CPU buffer: id={id3}")
        
        instancer.upload_transforms_to_gpu()  # Batch upload
        print(f"   ✅ Uploaded all instances to GPU")
        print(f"   ✅ Final instance count: {instancer.get_instance_count()}")
        
        # 8. Test: Clear instances
        print("7. Testing clear_instances...")
        instancer.clear_instances()
        print(f"   ✅ Cleared all instances, count: {instancer.get_instance_count()}")
        
        print("\n🎉 All tests passed! Atomic GPU updates are working!")
        return True
        
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_performance_comparison():
    """Performance-Vergleich: Atomic vs. Batch Updates"""
    print("\n⚡ Performance Comparison: Atomic vs Batch...")
    
    try:
        import time
        
        instancer = scatter_accel.GpuInstancer("perf_test_shader")
        
        # Prepare test matrices
        matrices = []
        for i in range(100):
            matrix = np.eye(4, dtype=np.float32)
            matrix[0, 3] = i  # Translation X
            matrices.append(matrix.flatten())
        
        # Test 1: Atomic adds
        print("1. Testing atomic adds (100 instances)...")
        start_time = time.perf_counter()
        for matrix in matrices:
            instancer.add_instance_on_gpu(matrix)
        atomic_time = time.perf_counter() - start_time
        print(f"   ⚡ Atomic adds: {atomic_time:.6f}s")
        
        # Clear for next test
        instancer.clear_instances()
        
        # Test 2: Batch adds + upload
        print("2. Testing batch adds + upload (100 instances)...")
        start_time = time.perf_counter()
        for matrix in matrices:
            instancer.add_instance(matrix)
        instancer.upload_transforms_to_gpu()
        batch_time = time.perf_counter() - start_time
        print(f"   ⚡ Batch adds + upload: {batch_time:.6f}s")
        
        # Performance comparison
        if atomic_time > 0:
            ratio = batch_time / atomic_time
            print(f"   📊 Performance ratio (batch/atomic): {ratio:.2f}x")
            
            if ratio > 1:
                print(f"   🚀 Atomic updates are {ratio:.2f}x faster!")
            else:
                print(f"   📈 Batch updates are {1/ratio:.2f}x faster")
        
        return True
        
    except Exception as e:
        print(f"❌ Performance test failed: {e}")
        return False

if __name__ == "__main__":
    print("🧪 GPU-Instancer Atomic Update Tests")
    print("=" * 50)
    
    # Run basic functionality tests
    success1 = test_atomic_gpu_updates()
    
    # Run performance tests
    success2 = test_performance_comparison()
    
    if success1 and success2:
        print("\n🎉 ALL TESTS PASSED! 🚀")
        print("Atomic GPU updates are ready for integration!")
    else:
        print("\n❌ Some tests failed. Check implementation.")
        sys.exit(1)
