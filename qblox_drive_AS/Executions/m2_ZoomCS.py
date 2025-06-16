from qblox_drive_AS.support.ExpFrames import Zoom_CavitySearching
from qblox_drive_AS.support.Path_Book import find_latest_QD_pkl_for_dr
from qblox_drive_AS.support import Data_manager
#// Test okay.

''' fill in '''
Execution:bool = True
DRandIP = {"dr":"dr3","last_ip":"13"}
freq_range:dict = {"q0":[5.91e9, 5.93e9],
                   "q1":[5.96e9, 5.98e9],
                   "q2":[6.005e9, 6.015e9],
                   "q3":[6.07e9, 6.09e9],
                   "q4":[6.09e9, 6.105e9],
                   }
freq_pts:int = 100
AVG:int = 100

''' Don't Touch '''
save_dir = Data_manager().build_packs_folder()
EXP = Zoom_CavitySearching(QD_path=find_latest_QD_pkl_for_dr(DRandIP["dr"],DRandIP["last_ip"]),data_folder=save_dir)
EXP.SetParameters(freq_range,freq_pts,AVG,Execution)
EXP.WorkFlow()
EXP.RunAnalysis()

