from qblox_drive_AS.support.Path_Book import find_latest_QD_pkl_for_dr
from qblox_drive_AS.support import Data_manager
from qblox_drive_AS.support.ExpFrames import EnergyRelaxation
#// test okay


''' fill in '''
Execution:bool = True
DRandIP = {"dr":"dr3","last_ip":"13"}
time_range:dict = {"q2":[0,80e-6]}
time_sampling_func:str = "linspace"
time_ptsORstep:int|float = 100
AVG:int = 500
histo_counts:int = 1
use_OnsShot:bool = False

''' Don't Touch '''
save_dir = Data_manager().build_packs_folder()
EXP = EnergyRelaxation(QD_path=find_latest_QD_pkl_for_dr(DRandIP["dr"],DRandIP["last_ip"]),data_folder=save_dir)
EXP.SetParameters(time_range,time_sampling_func,time_ptsORstep,histo_counts,AVG,Execution,use_OnsShot)
EXP.WorkFlow()
EXP.RunAnalysis()