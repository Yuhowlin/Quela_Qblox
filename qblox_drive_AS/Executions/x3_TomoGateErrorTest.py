from qblox_drive_AS.support.Path_Book import find_latest_QD_pkl_for_dr
from qblox_drive_AS.support import Data_manager
from qblox_drive_AS.support.ExpFrames import XTomography
#// test okay.

''' fill in '''
Execution: bool = 1
DRandIP = {"dr": "dr2", "last_ip": "10"}
target_q: list = ["q0"]
un_trained_pulse: bool = True
gate_counts = range(5)
avg_n: int = 1000
init_state: str = "zero" 
''' Don't Touch '''
save_dir = Data_manager().build_packs_folder()
EXP = XTomography(QD_path=find_latest_QD_pkl_for_dr(DRandIP["dr"], DRandIP["last_ip"]), data_folder=save_dir)
EXP.SetParameters(target_q, init_state, avg_n, gate_counts, Execution)
EXP.WorkFlow()
EXP.RunAnalysis()