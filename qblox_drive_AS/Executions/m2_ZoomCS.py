from qblox_drive_AS.support.ExpFrames import Zoom_CavitySearching
from qblox_drive_AS.Calibration_exp.TofCali import TofCalirator
from qblox_drive_AS.support.Path_Book import find_latest_QD_pkl_for_dr
from qblox_drive_AS.support import Data_manager


''' fill in '''
Execution:bool = 1
DRandIP = {"dr":"dr1","last_ip":"11"}
freq_range:dict = {
                    "q0":[4.56e9, 4.566e9],
                    "q1":[4.655e9, 4.665e9],
                    "q2":[4.752e9, 4.757e9],
                    "q3":[4.845e9, 4.855e9],
                   }
freq_pts:int = 100
AVG:int = 100

''' Don't Touch '''
save_dir = Data_manager().build_packs_folder()
EXP = Zoom_CavitySearching(QD_path=find_latest_QD_pkl_for_dr(DRandIP["dr"],DRandIP["last_ip"]),data_folder=save_dir)
EXP.SetParameters(freq_range,freq_pts,AVG,Execution)
EXP.WorkFlow()
EXP.RunAnalysis()


""" Go do c0 please """
