states = ["plus_i","zero","plus"]
shotnums = [500, 1000, 2000, 5000, 10000]
q = ["q0","q2","q3"]
fre = ["09995","09996","09997","09998","09999","10000","10001","10002","10003","10004","10005"]
from qcodes import Instrument
import time
for l in range(5):
    for m in fre:
        from qblox_drive_AS.support.Path_Book import find_latest_QD_pkl_for_dr
        from qblox_drive_AS.support import Data_manager
        from qblox_drive_AS.support.ExpFrames import XTomography
        #// test okay.

        ''' fill in '''
        Execution: bool = 1
        DRandIP = {"dr": "dr1", "last_ip": "11"}
        target_q: list = ["q2"]
        un_trained_pulse: bool = True
        maxmum_gate = 101
        avg_n: int = 5000
        init_state: str = "zero" # zero plus plus_i
        ''' Don't Touch '''
        gate_counts = range(maxmum_gate)
        save_dir = Data_manager().build_packs_folder()
        EXP = XTomography(QD_path=f"/Users/kelab_01/Documents/GitHub/Quela_Qblox/qblox_drive_AS/QD_backup/20260104/DR1#11_SumInfo{m}.pkl", data_folder=save_dir)
        EXP.SetParameters(target_q, init_state, avg_n, gate_counts, Execution)
        EXP.WorkFlow()
        EXP.RunAnalysis(m)
        Instrument.close_all()


# for k in shotnums:
#     for j in range(min(8, int(30000/k))):
#         for i in states:
#             from qblox_drive_AS.support.Path_Book import find_latest_QD_pkl_for_dr
#             from qblox_drive_AS.support import Data_manager
#             from qblox_drive_AS.support.ExpFrames import XTomography
#             #// test okay.

#             ''' fill in '''
#             Execution: bool = 1
#             DRandIP = {"dr": "dr1", "last_ip": "11"}
#             target_q: list = ["q2"]
#             un_trained_pulse: bool = True
#             maxmum_gate = 100
#             avg_n: int = k
#             init_state: str = i # zero plus plus_i
#             ''' Don't Touch '''
#             gate_counts = range(maxmum_gate)
#             save_dir = Data_manager().build_packs_folder()
#             EXP = XTomography(QD_path=find_latest_QD_pkl_for_dr(DRandIP["dr"], DRandIP["last_ip"]), data_folder=save_dir)
#             EXP.SetParameters(target_q, init_state, avg_n, gate_counts, Execution)
#             EXP.WorkFlow()
#             EXP.RunAnalysis(i,k)
#             Instrument.close_all()