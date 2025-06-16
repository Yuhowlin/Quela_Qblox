from qblox_drive_AS.support.Path_Book import find_latest_QD_pkl_for_dr
from qblox_drive_AS.support import Data_manager
from qblox_drive_AS.support.ExpFrames import SingleShot
#// test okay.

''' fill in '''
Execution:bool = 1
DRandIP = {"dr":"dr3","last_ip":"13"}
target_qs:list = ["q2",]
shots:int = 10000
histo_counts:int = 1

''' Don't Touch '''
save_dir = Data_manager().build_packs_folder()
EXP = SingleShot(QD_path=find_latest_QD_pkl_for_dr(DRandIP["dr"],DRandIP["last_ip"]),data_folder=save_dir)
EXP.SetParameters(target_qs,histo_counts,shots,Execution)
EXP.WorkFlow()
EXP.RunAnalysis(histo_ana=True if histo_counts > 1 else False)