from karma.core.persistence import PersistenceLayer, PersistenceConfig
from pathlib import Path
import os
import sys

config = PersistenceConfig(framework_dir=Path("./tmp_fw"))
p = PersistenceLayer(config)
try:
    with p.transaction():
        print("Tx 1")
        with p.transaction():
            print("Tx 2")
    print("Success")
except Exception as e:
    print(f"Error: {e}")
