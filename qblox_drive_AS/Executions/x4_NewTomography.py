from qblox_drive_AS.support.Path_Book import find_latest_QD_pkl_for_dr
from qblox_drive_AS.support import Data_manager
from qblox_drive_AS.support.ExpFrames import AdvancedTomography

''' fill in '''
Execution: bool = 1
DRandIP = {"dr": "dr1", "last_ip": "11"}

# 1. 全域量測參數 (Global Measurement Settings)
avg_n: int = 10000               
training_avg_n: int = 20000      
symmetrized_readout: bool = True 
gate_counts = range(3)         # ✅ 統一的掃描長度

# 2. 獨立的量子位元參數控制 (不再需要個別設定 gate_counts)
qubit_configs = {
    "q1": {
        "init_state": "0",       
        "target_gate": "X",      
    },
    "q2": {
        "init_state": "+",
        "target_gate": "Y90",
    }
}

''' Don't Touch '''
save_dir = Data_manager().build_packs_folder()
EXP = AdvancedTomography(
    QD_path=find_latest_QD_pkl_for_dr(DRandIP["dr"], DRandIP["last_ip"]), 
    data_folder=save_dir
)

# 參數傳遞更新
EXP.SetParameters(
    qubit_configs=qubit_configs,
    gate_counts=gate_counts,    # ✅ 傳入統一的 gate_counts
    avg_n=avg_n,
    training_avg_n=training_avg_n,
    symmetrized_readout=symmetrized_readout,
    execution=Execution
)

EXP.WorkFlow()
EXP.RunAnalysis()