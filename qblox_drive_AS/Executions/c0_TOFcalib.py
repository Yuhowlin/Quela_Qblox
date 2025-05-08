''' m2 will do it automatically '''
from qblox_drive_AS.Calibration_exp.TofCali import TofCalirator
from qblox_drive_AS.support.Path_Book import find_latest_QD_pkl_for_dr
from qblox_drive_AS.support import Data_manager

""" Fill in """
DRandIP = {"dr":"dr1","last_ip":"11"}
q = "q1"


""" Do NOT touch !! """
save_dir = Data_manager().build_packs_folder()
CAL = TofCalirator(save_dir)
CAL.QD_path = find_latest_QD_pkl_for_dr(DRandIP["dr"],DRandIP["last_ip"])
CAL.q = q
CAL.WorkFlow()
CAL.RunAnalysis()