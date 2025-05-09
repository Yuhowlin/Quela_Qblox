import pickle, os
from typing import Callable
from qblox_drive_AS.Configs.ClusterAddress_rec import ip_register, port_register
from qcodes.instrument import find_or_create_instrument
from typing import Tuple
import ipywidgets as widgets
from IPython.display import display
from quantify_scheduler.helpers.collections import find_port_clock_path
from qblox_instruments import Cluster, PlugAndPlay, ClusterType
# from qblox_instruments.qcodes_drivers.qcm_qrm import QcmQrm
from qcodes import Instrument
from quantify_core.measurement.control import MeasurementControl
from quantify_core.visualization.pyqt_plotmon import PlotMonitor_pyqt as PlotMonitor
from quantify_scheduler.device_under_test.quantum_device import QuantumDevice
from quantify_scheduler.instrument_coordinator import InstrumentCoordinator
from quantify_scheduler.instrument_coordinator.components.qblox import ClusterComponent
from utils.tutorial_utils import (
    set_drive_attenuation,
    set_readout_attenuation,
)
from quantify_core.data.handling import gen_tuid
from quantify_core.analysis.readout_calibration_analysis import (
    ReadoutCalibrationAnalysis,
)
from xarray import Dataset
from qblox_drive_AS.support.QDmanager import QDmanager, Data_manager, BasicTransmonElement
import qblox_drive_AS.support.UI_Window as uw
import qblox_drive_AS.support.Chip_Data_Store as cds
from numpy import ndarray
from numpy import asarray, real, vstack, array, imag, arange
from numpy import arctan2, pi, cos, sin, exp, rad2deg
from qblox_drive_AS.support.UserFriend import *

import quantify_core.data.handling as dh
meas_datadir = '.data'
dh.set_datadir(meas_datadir)

def qs_on_a_boat(hcfg:dict, q:str='q')->list:
    qs = []
    for name in hcfg["hardware_options"]["modulation_frequencies"]:
        if name.split("-")[0]==f"{q}:res":
            q_on_same_boat = name.split("-")[-1].split(".")[0]
            qs.append(q_on_same_boat)
    return qs

def multiples_of_x(raw_number:float, x:float):
    multiples = int(raw_number//x) + 1
    return x * multiples
    
def check_acq_channels(QD_agent:QDmanager, join_measure_qs:list)->QDmanager:
    join_measure_qs.sort(key=lambda x: int(x[1:]))
    for idx, q in enumerate(join_measure_qs):
        QD_agent.quantum_device.get_element(q).measure.acq_channel(idx)
    
    return QD_agent

def sort_dict_with_qidx(D:dict|list)->dict|list:
    """ Expect the every key names in D starts with q, like 'q1', 'q2', 'q99', etc. """
    if isinstance(D, dict):
        return dict(sorted(D.items(), key=lambda x: int(x[0][1:])))
    elif isinstance(D, list):
        return sorted(D, key=lambda x: int(x[1:]))
    else:
        raise TypeError("Arg must be a dict or list !")


def find_nearest(ary:ndarray, value:float):
    """ find the element  which is closest to the given target_value in the given array"""
    ary = asarray(ary)
    idx = (abs(ary - value)).argmin()
    return float(ary[idx])

# initialize a measurement
def init_meas(QuantumDevice_path:str)->Tuple[QDmanager, Cluster, MeasurementControl, InstrumentCoordinator, dict]:
    """
    Initialize a measurement by the following 2 cases:\n
    ### Case 1: QD_path isn't given, create a new QD accordingly.\n
    ### Case 2: QD_path is given, load the QD with that given path.\n
    args:\n
    mode: 'new'/'n' or 'load'/'l'. 'new' need a self defined hardware config. 'load' load the given path. 
    """
    from qblox_drive_AS.support.UserFriend import warning_print
    
    cfg, pth = {}, QuantumDevice_path 
    dr_loc = get_dr_loca(QuantumDevice_path)
    cluster_ip = ip_register[dr_loc.lower()]

    
    if cluster_ip in list(port_register.keys()):
        # try maximum 3 connections to prevent connect timeout error 
        try:
            cluster = Cluster(name = f"cluster{dr_loc.lower()}",identifier = f"qum.phys.sinica.edu.tw", port=int(port_register[cluster_ip]))
            
        except:
            try:
                warning_print("First cluster connection trying")
                cluster = Cluster(name = f"cluster{dr_loc.lower()}",identifier = f"qum.phys.sinica.edu.tw", port=int(port_register[cluster_ip]))
            except:
                warning_print("Second cluster connection trying")
                cluster = Cluster(name = f"cluster{dr_loc.lower()}",identifier = f"qum.phys.sinica.edu.tw", port=int(port_register[cluster_ip]))          
    else:
        try:
            warning_print("cluster IP connection trying")
            cluster = Cluster(name = f"cluster{dr_loc.lower()}", identifier = cluster_ip)
        except:
            raise KeyError("Check your cluster ip had been log into Experiment_setup.py with its connected DR, and also is its ip-port")
    
    ip = ip_register[dr_loc.lower()]
    
    # enable_QCMRF_LO(cluster) # for v0.6 firmware
    Qmanager = QDmanager(pth)
    Qmanager.QD_loader()

    QRM_nco_init(cluster, int(Qmanager.Notewriter.get_NcoPropDelay()*1e9))
    bias_controller = Qmanager.activate_str_Fctrl(cluster)

    meas_ctrl, ic = configure_measurement_control_loop(Qmanager.quantum_device, cluster)
    reset_offset(bias_controller)
    cluster.reset()

    return Qmanager, cluster, meas_ctrl, ic, bias_controller

def get_ip_specifier(QD_path:str):
    specifier = QD_path.split("#")[-1].split("_")[0]
    return specifier 

def get_dr_loca(QD_path:str):
    loc = os.path.split(QD_path)[-1].split("#")[0]
    return loc

# Configure_measurement_control_loop
""""# for firmware v0.6.2
def configure_measurement_control_loop(
    device: QuantumDevice, cluster: Cluster, live_plotting: bool = False
    ) ->Tuple[MeasurementControl,InstrumentCoordinator]:
    # Close QCoDeS instruments with conflicting names
    for name in [
        "PlotMonitor",
        "meas_ctrl",
        "ic",
        "ic_generic",
        f"ic_{cluster.name}",
        ] + [f"ic_{module.name}" for module in cluster.modules]:
        try:
            Instrument.find_instrument(name).close()
        except KeyError as kerr:
            pass

    meas_ctrl = MeasurementControl("meas_ctrl")
    ic = InstrumentCoordinator("ic")
    ic.timeout(60*60)

    # Add cluster to instrument coordinator
    ic_cluster = ClusterComponent(cluster)
    ic.add_component(ic_cluster)

    if live_plotting:
        # Associate plot monitor with measurement controller
        plotmon = PlotMonitor("PlotMonitor")
        meas_ctrl.instr_plotmon(plotmon.name)

    # Associate measurement controller and instrument coordinator with the quantum device
    device.instr_measurement_control(meas_ctrl.name)
    device.instr_instrument_coordinator(ic.name)

    return (meas_ctrl, ic)
"""
# for firmware v0.7.0
def configure_measurement_control_loop(
    device: QuantumDevice, cluster: Cluster, live_plotting: bool = False
    ) ->Tuple[MeasurementControl,InstrumentCoordinator]:
    meas_ctrl = find_or_create_instrument(MeasurementControl, recreate=True, name="meas_ctrl")
    ic = find_or_create_instrument(InstrumentCoordinator, recreate=True, name="ic")
    ic.timeout(60*60*120) # 120 hr maximum
    # Add cluster to instrument coordinator
    ic_cluster = ClusterComponent(cluster)
    ic.add_component(ic_cluster)

    if live_plotting:
        # Associate plot monitor with measurement controller
        plotmon = find_or_create_instrument(PlotMonitor, recreate=False, name="PlotMonitor")
        meas_ctrl.instr_plotmon(plotmon.name)

    # Associate measurement controller and instrument coordinator with the quantum device
    device.instr_measurement_control(meas_ctrl.name)
    device.instr_instrument_coordinator(ic.name)

    return (meas_ctrl, ic)



# close all instruments
def shut_down(cluster:Cluster,flux_map:dict):
    '''
        Disconnect all the instruments.
    '''
    reset_offset(flux_map)
    cluster.reset() 
    Instrument.close_all() 
    print("All instr are closed and zeroed all flux bias!")

# connect to clusters
def connect_clusters():
    with PlugAndPlay() as p:            # Scan for available devices and display
        device_list = p.list_devices()  # Get info of all devices

    names = {dev_id: dev_info["description"]["name"] for dev_id, dev_info in device_list.items()}
    ip_addresses = {dev_id: dev_info["identity"]["ip"] for dev_id, dev_info in device_list.items()}
    connect_options = widgets.Dropdown(         # Create widget for names and ip addresses *** Should be change into other interface in the future
        options=[(f"{names[dev_id]} @{ip_addresses[dev_id]}", dev_id) for dev_id in device_list],
        description="Select Device",
    )
    display(connect_options)
    
    return connect_options, ip_addresses

# Multi-clusters online version connect_clusters()
def connect_clusters_withinMulti(dr_loc:str,ip:str='192.168.1.10'):
    """
    This function is only for who doesn't use jupyter notebook to connect cluster.
    args: \n
    ip: 192.168.1.10\n
    So far the ip for Qblox cluster is named with 192.168.1.170 and 192.168.1.171
    """

    permissions = {}
    with PlugAndPlay() as p:            # Scan for available devices and display
        device_list = p.list_devices()
    for devi, info in device_list.items():
        permissions[info["identity"]["ip"]] = info["identity"]["ser"]
    if ip in permissions:
        print(f"{ip} is available to connect to!")
        return ip, permissions[ip]
    else:
        raise KeyError(f"{ip} is NOT available now!")
 
# def set attenuation for all qubit
def oldver_set_atte_for(quantum_device:QuantumDevice,atte_value:int,mode:str,target_q:list=['q1']):
    """
        Set the attenuations for RO/XY by the given mode and atte. values.\n
        atte_value: integer multiple of 2,\n
        mode: 'ro' or 'xy',\n
        target_q: ['q1']
    """
    # Check atte value
    if atte_value%2 != 0:
        raise ValueError(f"atte_value={atte_value} is not the multiple of 2!")
    # set atte.
    if mode.lower() == 'ro':
        for q_name in target_q:
            set_readout_attenuation(quantum_device, quantum_device.get_element(q_name), out_att=atte_value, in_att=0)
    elif mode.lower() == 'xy':
        for q_name in target_q:
            try:
                driving_port_path = find_port_clock_path(quantum_device.hardware_config(),f"{q_name}:mw",f"{q_name}.01")
                set_drive_attenuation(quantum_device, quantum_device.get_element(q_name), out_att=atte_value)
            except Exception as err:
                print(f"!!!!! Can't fing the driving port for {q_name}, cancel setting its xy-attenuation !!!!!!")
    else:
        raise KeyError (f"The mode='{mode.lower()}' is not 'ro' or 'xy'!")

# new version 
def set_atte_for(quantum_device:QuantumDevice,atte_value:int,mode:str,target_q:list=['q1']):
    """
        Set the attenuations for RO/XY by the given mode and atte. values.\n
        atte_value: integer multiple of 2,\n
        mode: 'ro' or 'xy',\n
        target_q: ['q1']
    """
    
    # Check atte value
    if atte_value%2 != 0:
        raise ValueError(f"atte_value={atte_value} is not the multiple of 2!")
    # set atte.
    if mode.lower() == 'ro':
        for q_name in target_q:
            quantum_device.hardware_config()["hardware_options"]["output_att"][f"{q_name}:res-{q_name}.ro"] = atte_value
    elif mode.lower() == 'xy':
        
        for q_name in target_q:
            try:
                quantum_device.hardware_config()["hardware_options"]["output_att"][f"{q_name}:mw-{q_name}.01"] = atte_value
            except Exception as err:
                print(f"!!!!! Can't fing the driving port for {q_name}, cancel setting its xy-attenuation !!!!!!")
    else:
        raise KeyError (f"The mode='{mode.lower()}' is not 'ro' or 'xy'!")
    


def reset_offset(flux_callable_map:dict):
    for i in flux_callable_map:
        flux_callable_map[i](0.0)


# def add log message into the sumInfo
def leave_LogMSG(MSG:str,sumInfo_path:str):
    """
    Leave the log message in the sumInfo with the given path.
    """
    with open(sumInfo_path, 'rb') as inp:
        gift = pickle.load(inp)
    gift["Log"] = MSG
    with open(sumInfo_path, 'wb') as file:
        pickle.dump(gift, file)
        print("Log message had been added!")


# set attenuations
def init_system_atte(quantum_device:QuantumDevice,qb_list:list,ro_out_att:int=None,xy_out_att:int=None):
    """
    Attenuation setting includes XY and RO. We don't change it once we set it.
    """
    # atte. setting
    if ro_out_att is not None:
        set_atte_for(quantum_device,ro_out_att,'ro',qb_list)
    
    if xy_out_att is not None:
        set_atte_for(quantum_device,xy_out_att,'xy',qb_list) 


# LO debug
def get_connected_modules(cluster: Cluster, filter_fn: Callable):
    def checked_filter_fn(mod: ClusterType) -> bool:
        if filter_fn is not None:
            return filter_fn(mod)
        return True
   
    return {
        mod.slot_idx: mod for mod in cluster.modules if mod.present() and checked_filter_fn(mod)
    }





def QRM_nco_init(cluster, prop_delay_ns:float=50):
    slightly_print(f"Recieved nco_prop_delay = {prop_delay_ns} ns")
    QRM_RFs = get_connected_modules(cluster,lambda mod: mod.is_qrm_type)
    for slot_idx in QRM_RFs:
        for i in range(6):
            getattr(QRM_RFs[slot_idx], f"sequencer{i}").nco_prop_delay_comp_en(True)      
            getattr(QRM_RFs[slot_idx], f"sequencer{i}").nco_prop_delay_comp(prop_delay_ns)
    
    print(f" NCO in QRM_RF: {list(QRM_RFs.keys())} had initialized NCO successfully!")


def advise_where_fq(QD:QDmanager,target_q:str,guess_g_Hz:float=48e6):
    fb = QD.Notewriter.get_bareFreqFor(target_q)
    fd = QD.quantum_device.get_element(target_q).clock_freqs.readout()
    g = guess_g_Hz
    x = fd-fb
    fq_Hz = fb - (g**2)/x
    return fq_Hz


def check_QD_info(QD_agent:QDmanager,target_q:str):
    from utils.tutorial_utils import show_readout_args, show_drive_args
    qubit = QD_agent.quantum_device.get_element(target_q)
    show_readout_args(qubit)
    show_drive_args(qubit)

def coupler_zctrl(Fctrl:dict,cp_elements:dict)->dict:
    """
    control coupler Z bias.
    ------------------------------
    # * Args:\n
    cp_elements follows the form: `{ coupler_name:bias (V)}`, like `{"c0":0.2}`
    ------------------------------
    # * Example:\n
    coupler_zctrl(dr2,cluster,cp_elements={"c0":0.2})
    ------------------------------
    """
    
    for cp in cp_elements:
        slightly_print(f"{cp} biased @ {round(cp_elements[cp],2)} V")
        Fctrl[cp](cp_elements[cp])
    
    return Fctrl

def compose_para_for_multiplexing(QD_agent:QDmanager,ro_elements,mode:str)->dict:
    """
    Get the dict about the required values for all qubits in quantum_device.
    The required value can be assigned by the arg `mode`.
    ------
    ### Args:\n
    * ro_elements: a dict with the keyname in qubit name. ex: {"q0":[ ],"q1":[ ],...}\n
    * mode:\n 
        'r1' for RO-amp, 'r2' for acq-delay, 'r3' for RO-duration, 'r4' for integration time.\n
        'd1' for xy-amp,                     'd3' for xy-duration,
    ----
    ### Returns:\n
    A dict with the same keyname as the `ro_elements`, and also with the value about the required mode.  
    """
    if type(ro_elements) is dict:
        qubits = list(ro_elements.keys())
    elif type(ro_elements) is list:
        qubits:list = ro_elements
    else:
        raise ValueError(f"The type of ro_elements should be list or dict but `{type(ro_elements)}` was recieved!")
    ans = {}
    for qubit in qubits:
        match mode.lower():
            case "r1":
                ans[qubit] = QD_agent.quantum_device.get_element(qubit).measure.pulse_amp()
            case "r2":
                ans[qubit] = QD_agent.quantum_device.get_element(qubit).measure.acq_delay()
            case "r3":
                ans[qubit] = QD_agent.quantum_device.get_element(qubit).measure.pulse_duration()
            case "r4":
                ans[qubit] = QD_agent.quantum_device.get_element(qubit).measure.integration_time()
            case 'd1':
                ans[qubit] = QD_agent.quantum_device.get_element(qubit).rxy.amp180()
            case 'd3':
                ans[qubit] = QD_agent.quantum_device.get_element(qubit).rxy.duration()
            case _:
                raise KeyError(f"Un-supported mode = {mode} was given !")
    
    return ans

def rotation_matrix(angle)->ndarray:
    rotate_matrix = array([
        [cos(angle), -sin(angle)],
        [sin(angle),  cos(angle)]
    ])
    return rotate_matrix

def rotate_onto_Inphase(point_1:ndarray, point_2:ndarray, angle_degree:float=None)->tuple[ndarray,float]:
    """
        Give 2 points, rotate them makes them lie one the x-axis and return the rotate angle in degree.\n
        If you also give the rotate angle in degree, we rotate them according to this angle.
    """
    vector_21 = (point_2 - point_1)
    
    if angle_degree is None:
        angle_degree = rad2deg(arctan2(vector_21[1], vector_21[0])) % 360 # Angle to align with x-axis
        
    angle = angle_degree*pi/180
    data = array([[point_1[0], point_2[0]],[point_1[1], point_2[1]]])
    rotated = rotate_data(data, angle)


    return rotated, angle_degree


def rotate_data(data:ndarray, angle_degree:float)->ndarray:
    """ data shape (IQ, shots) """

    angle = angle_degree*pi/180
    S21 = data[0] + 1j*data[1] 

    roted_S21 = array(S21*exp(-1j*angle))
    data_rotated = array([real(roted_S21).tolist(), imag(roted_S21).tolist()])

    return data_rotated

def set_LO_frequency(quantum_device:QuantumDevice,q:str,module_type:str,LO_frequency:float):
    hw_config = quantum_device.hardware_config()
    match module_type.lower():
        case 'drive':
            hw_config["hardware_options"]["modulation_frequencies"][f"{q}:mw-{q}.01"]["lo_freq"] = LO_frequency
        case 'readout':
            for name in hw_config["hardware_options"]["modulation_frequencies"]:
                if name.split("-")[0] == f"{q}:res":
                    hw_config["hardware_options"]["modulation_frequencies"][name]["lo_freq"] = LO_frequency
   
    quantum_device.hardware_config(hw_config)

def check_OS_model_ready(QD_agent:QDmanager, qs:list):
    OS_models = QD_agent.StateDiscriminator.elements
    for q in qs:
        if q not in OS_models:
            QD_agent.StateDiscriminator.summon_discriminator(q) # will raise NameError


def ReadoutFidelity_acq_analyzer(QD_agent:QDmanager, dataset:Dataset, ask_repe_idx:bool=False)->QDmanager:
    repe_idx_to_fit = 0
    
    if dataset.coords["repeat"].size > 1:
        if ask_repe_idx:
            repe_idx_to_fit = int(input(f"There are {dataset.coords['repeat'].size} repetitions, what index of repetition you will use to fit ? [0~{dataset.coords['repeat'].size-1}]"))
        
    for q in dataset.data_vars:
        dict_ = {}
        I = array(dataset.data_vars[q].values[repe_idx_to_fit][0])
        Q = array(dataset.data_vars[q].values[repe_idx_to_fit][1])
        dict_["y0"] = ("dim_0", I.transpose().reshape(-1))
        dict_["y1"] = ("dim_0", Q.transpose().reshape(-1))
        n_dataset = Dataset(dict_,coords={"x0":("dim_0", array([0,1]*dataset.coords['index'].size))})
        n_dataset.y0.attrs['units'] = "V"
        n_dataset.y1.attrs['units'] = "V"
        n_dataset.attrs = dataset.attrs
        n_dataset.attrs["tuid"] = gen_tuid()
        n_dataset.attrs["name"] = f"{q}_Readout_Fidelity"
        analysis = ReadoutCalibrationAnalysis(n_dataset)
        analysis.run()
        fit_results = analysis.fit_results["linear_discriminator"].params   
        acq_threshold = fit_results["acq_threshold"].value
        acq_rotation = (rad2deg(fit_results["acq_rotation_rad"].value)) % 360
        qubit_element:BasicTransmonElement = QD_agent.quantum_device.get_element(q)
        qubit_element.measure.acq_threshold(acq_threshold)
        qubit_element.measure.acq_rotation(acq_rotation)
        
    return QD_agent

if __name__ == "__main__":
    check_acq_channels(QD_agent="", join_measure_qs=["q0", "q12", "q3", "q9", "q4"])