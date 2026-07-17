import threading
import uuid
import time
from pathlib import Path

from karma.core.persistence import PersistenceConfig, PersistenceLayer
from karma.turn_kernel import handle_turn, TurnRequest

def worker(persistence, project_name, worker_id):
    for i in range(5):
        req = TurnRequest(
            project=project_name,
            request_id=f"req_{worker_id}_{i}",
            task=f"task_{worker_id}_{i}",
            content="def dummy(): pass\n",
            skill_name="test_skill",
        )
        try:
            res = handle_turn(persistence, req)
            print(f"[Worker {worker_id}] Turn {i} completed. Gate passed: {res.gate_passed}")
        except Exception as e:
            print(f"[Worker {worker_id}] Turn {i} failed: {e}")
            raise e

def main():
    config = PersistenceConfig(framework_dir=Path("./tmp_test_parallel"))
    persistence = PersistenceLayer(config)
    
    threads = []
    start_time = time.time()
    for i in range(10):  # 10 concurrent agents
        t = threading.Thread(target=worker, args=(persistence, "test_proj", i))
        threads.append(t)
        t.start()
        
    for t in threads:
        t.join()
        
    print(f"Parallel test finished in {time.time() - start_time:.2f}s")
    
if __name__ == "__main__":
    main()
