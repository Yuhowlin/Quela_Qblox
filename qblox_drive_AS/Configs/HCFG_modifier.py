from os import path
import rich
from qblox_drive_AS.support.QDmanager import QDmanager, hcfg_composer
from qblox_drive_AS.support.UserFriend import mark_input, slightly_print
####### Port Name rules #######
# 1. Driving port: ":mw", like 'q1:mw', 'q2:mw', ...
# 2. Readout port: ":res", like 'q0:res', 'q3:res', ...
# 3. Flux bias port: ":fl", like 'q12:fl', 'q999:fl', ...


""" Fill in """
QD_path = r"C:\Users\ASUS\Documents\GitHub\Quela_Qblox\qblox_drive_AS\QD_backup\20250804\DR2#10_SumInfo.pkl"
Hcfg = [
    {"name":"q0:mw", "slot":4, "port":0},
    {"name":"q0:res", "slot":8, "port":0},
    {"name":"q1:res", "slot":8, "port":0},
    {"name":"q2:res", "slot":8, "port":0},
    {"name":"q3:res", "slot":8, "port":0},
    {"name":"q0:fl", "slot":2, "port":2},
    {"name":"q1:fl", "slot":2, "port":1},
    {"name":"q2:fl", "slot":2, "port":3},
    {"name":"q3:fl", "slot":2, "port":0},
]


""" Do NOT touch !!! """
QD_agent = QDmanager(QD_path)
QD_agent.QD_loader(new_Hcfg=hcfg_composer(Hcfg, dr_name=path.split(QD_path)[-1].split("#")[0].lower()))
rich.print(QD_agent.quantum_device.hardware_config())

permission = mark_input("Is this HCFG correct ? [y/n]")
if permission.lower() in ['y', 'yes']:
    QD_agent.QD_keeper()
else:
    slightly_print("Permission got denied ~ ")