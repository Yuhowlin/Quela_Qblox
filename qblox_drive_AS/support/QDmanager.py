import os, datetime, pickle, rich
from xarray import Dataset
from qblox_drive_AS.support.UserFriend import *
from qblox_drive_AS.support.FluxBiasDict import FluxBiasDict
from qblox_drive_AS.support.Notebook import Notebook
from qblox_drive_AS.support.WaveformCtrl import GateGenesis
from qblox_instruments import Cluster
from quantify_scheduler.device_under_test.quantum_device import QuantumDevice
from quantify_scheduler.device_under_test.transmon_element import BasicTransmonElement
import matplotlib.pyplot as plt
from matplotlib.figure import Figure
from qblox_drive_AS.support.StatifyContainer import Statifier
from numpy import asarray

def ret_q(dict_a):
    x = []
    for i in dict_a:
        if i[0] == 'q':
            x.append(i)
    return x

def ret_c(dict_a):
    x = []
    for i in dict_a:
        if i[0] == 'c':
            x.append(i)
    return x

def find_path_by_port(hardware_config, port):
    """ By a port name, return a dict = {elements:[paths]} who use that port """
    answers = {}
    def recursive_find(hardware_config, port,  path) -> list | None:
        
        for k, v in hardware_config.items():
            # If key is port, we are done
            if k == "port":
                
                if (
                    port in hardware_config["port"]
                ):
                    answers[hardware_config["clock"].split(".")[0]] = path[1:3]

            # If value is list, append key to path and loop trough its elements.
            elif isinstance(v, list):
                path.append(k)  # Add list key to path.
                for i, sub_config in enumerate(v):
                    path.append(i)  # Add list element index to path.
                    if isinstance(sub_config, dict):
                        found_path = recursive_find(sub_config, port, path)
                        if found_path:
                            return found_path
                    path.pop()  # Remove list index if port-clock not found in element.
                path.pop()  # Remove list key if port-clock not found in list.

            # If dict append its key. If port is not found delete it
            elif isinstance(v, dict):
                path.append(k)
                found_path = recursive_find(v, port, path)
                if found_path:
                    return found_path
                path.pop()  # Remove dict key if port-clock not found in this dict.
        

    _ = recursive_find(hardware_config, port,path=[])
    if len(list(answers.keys())) == 0 :
        raise KeyError(
            f"The combination of {port=} could not be found in {hardware_config=}."
        )
    else:
        return answers

def find_path_by_clock(hardware_config, port, clock):
    """ By port and clock name, return a dict = {elements:[paths]} who use that port and the same clock """
    answers = {}
    def recursive_find(hardware_config, port, clock, path) -> list | None:
        
        for k, v in hardware_config.items():
            # If key is port, we are done
            if k == "port":
                if (
                    port in hardware_config["port"]
                    and hardware_config["clock"] == clock
                ):
                    answers[hardware_config["port"].split(":")[0]] = path[1:3]

            # If value is list, append key to path and loop trough its elements.
            elif isinstance(v, list):
                path.append(k)  # Add list key to path.
                for i, sub_config in enumerate(v):
                    path.append(i)  # Add list element index to path.
                    if isinstance(sub_config, dict):
                        found_path = recursive_find(sub_config, port, clock, path)
                        if found_path:
                            return found_path
                    path.pop()  # Remove list index if port-clock not found in element.
                path.pop()  # Remove list key if port-clock not found in list.

            # If dict append its key. If port is not found delete it
            elif isinstance(v, dict):
                path.append(k)
                found_path = recursive_find(v, port, clock, path)
                if found_path:
                    return found_path
                path.pop()  # Remove dict key if port-clock not found in this dict.
        

    _ = recursive_find(hardware_config, port, clock, path=[])
    if len(list(answers.keys())) == 0 :
        raise KeyError(
            f"The combination of {port=} and {clock=} could not be found in {hardware_config=}."
        )
    else:
        return answers

def find_q_same_QCMRF(connectivity:dict)->dict:
    pairs = {}
    for con in connectivity["graph"]:
        slot_idx = con[0].split(".")[1][6:]
        if slot_idx not in pairs:
            pairs[slot_idx] = []
        if con[-1].split(":")[-1] == 'mw':    
            pairs[slot_idx].append(con[-1])

    return pairs
        



def find_flux_lines(hcfg:dict)->dict:
    answer = {}
    for port_loc, port_name in hcfg["connectivity"]["graph"]:
        if port_name.split(":")[-1] == 'fl':
            answer[port_name.split(":")[0]] = port_loc
    return answer



def hcfg_composer(specs:list, dr_name:str)->dict:
    """
    specs: [{'name':port_name, 'slot':slot_idx, 'port':port_idx}, ...].
    ## port_name must follow the rules: 'q_name:type'. type in ['mw', 'res', 'fl'].
    ### - 'mw' for a driving port.
    ### - 'res' for a readout port.
    ### - 'fl' for a flux bias port.
    - Ex. 'q0:res', 'q1:mw', 'q2:fl' 
    """

    cluster_name = f"cluster{dr_name}"
    hcfg_connections = {"connectivity":{"graph":[]}}
    modules:dict = {}
    attes:dict = {}
    mixer_corrections:dict = {}
    modulation_frequencies:dict = {}

    for connection in specs:
        port_name:str = connection["name"]
        slot:int = connection["slot"]
        port_idx:int = connection["port"]

        match port_name.split(":")[-1]:
            case "mw":
                hcfg_connections["connectivity"]["graph"].append([f"{cluster_name}.module{slot}.complex_output_{port_idx}",port_name])
                tp = 'QCM_RF'
                port_clock_combi = f'{port_name}-{port_name.split(":")[0]}.01'
                attes[port_clock_combi] = 0
                mixer_corrections[port_clock_combi] = {"auto_lo_cal": "on_lo_interm_freq_change","auto_sideband_cal": "on_interm_freq_change"}
                modulation_frequencies[port_clock_combi] = {"lo_freq":4e9}
            case "res":
                hcfg_connections["connectivity"]["graph"].append([f"{cluster_name}.module{slot}.complex_output_{port_idx}",port_name])
                tp = 'QRM_RF'
                port_clock_combi = f'{port_name}-{port_name.split(":")[0]}.ro'
                attes[port_clock_combi] = 0
                mixer_corrections[port_clock_combi] = { "dc_offset_i": 0.0,
                                                        "dc_offset_q": 0.0,
                                                        "amp_ratio": 1.0,
                                                        "phase_error": 0.0 }
                modulation_frequencies[port_clock_combi] = {"lo_freq":6e9}
            case "fl":
                tp = 'QCM'
                hcfg_connections["connectivity"]["graph"].append([f"{cluster_name}.module{slot}.real_output_{port_idx}",port_name])
            case _:
                raise NameError(f"Unexpected port name was recieved: {port_name}.")

        modules[str(slot)] = {"instrument_type": tp}
    
    
    hcfg:dict = {
                 "config_type": "quantify_scheduler.backends.qblox_backend.QbloxHardwareCompilationConfig",
                 "allow_off_grid_nco_ops":True,
                 "connectivity":hcfg_connections["connectivity"]
                }

    
    hcfg["hardware_description"] = {cluster_name: {"instrument_type": "Cluster",
                                                   "modules": modules,
                                                   "sequence_to_file": False,
                                                   "ref": "internal"}}
    hcfg["hardware_options"] = {"output_att": attes,
                                "mixer_corrections": mixer_corrections,
                                "modulation_frequencies": modulation_frequencies}
    
    return hcfg
    

class QDmanager():
    def __init__(self,QD_path:str=''):
        self.manager_version:str = "v2.2" # Only RatisWu can edit it
        self.path = QD_path
        self.StateDiscriminator:Statifier = Statifier()
        self.Waveformer:GateGenesis = None
        self.machine_IP = ""
        self.refIQ = {}
        self.rotate_angle = {}
        self.Hcfg = {}
        self.Fctrl_str_ver = {}
        self.Log = "" 
        self.Identity=""
        self.chip_name = ""
        self.chip_type = ""
        self.DiscriminatorVersion:str = ""
        self.activeReset:bool = False

    def retrieve_complete_HCFG(self):
        qs = asarray(self.quantum_device.elements())
        HCFG = self.quantum_device.hardware_config()
        
        for q in qs:
            # fill in attenuations
            HCFG["hardware_options"]["output_att"][f'{q}:res-{q}.ro'] = self.Notewriter.get_DigiAtteFor(q, 'ro')
            HCFG["hardware_options"]["output_att"][f'{q}:mw-{q}.01'] = self.Notewriter.get_DigiAtteFor(q, 'xy')
            if f"{q}:mw-{q}.12" in HCFG["hardware_options"]["output_att"]:
                HCFG["hardware_options"]["output_att"][f"{q}:mw-{q}.12"] = self.Notewriter.get_DigiAtteFor(q, 'xy')
            
            # fill in XY-LO
        drive_port_pairs = find_q_same_QCMRF(HCFG["connectivity"])
        for slot in drive_port_pairs:
            xyf_sum = 0
            for port_name in drive_port_pairs[slot]:
                q = port_name.split(":")[0]
                xyf_sum += self.quantum_device.get_element(q).clock_freqs.f01()
            
            for port_name in drive_port_pairs[slot]:
                q = port_name.split(":")[0]
                HCFG["hardware_options"]["modulation_frequencies"][f'{q}:mw-{q}.01'] = {"lo_freq":round(xyf_sum/len(drive_port_pairs[slot]))} # LO = avg XYF with a same QCM-RF slot
        
        self.quantum_device.hardware_config(HCFG)
        


    
    def register(self,cluster_ip_adress:str,which_dr:str,chip_name:str='',chip_type = ''):
        """
        Register this QDmanager according to the cluster ip and in which dr and the chip name.
        """
        self.machine_IP = cluster_ip_adress
        self.Identity = which_dr.upper()+"#"+self.machine_IP.split(".")[-1] # Ex. DR2#171
        self.chip_name = chip_name
        self.chip_type = chip_type

    def made_mobileFctrl(self):
        """ Turn attrs about `cluster.module.out0_offset` into str."""
        self.Fctrl_str_ver = {}
        try:
            ans = find_flux_lines(self.Hcfg)
            qbits_registered = self.quantum_device.elements()
            
            for q in qbits_registered:
                if q in ans:
                    cluster_name = ans[q].split(".")[0]
                    module_name = ans[q].split(".")[1]
                    func_name = f"out{ans[q].split('_')[-1]}_offset"

                    self.Fctrl_str_ver[q] = f"{cluster_name}.{module_name}.{func_name}"
                else:
                    self.Fctrl_str_ver[q] = f"pass"
            # check couplers
            for ele in ans:
                if ele[0] == 'c':
                    cluster_name = ans[ele].split(".")[0]
                    module_name = ans[ele].split(".")[1]
                    func_name = f"out{ans[ele].split('_')[-1]}_offset"

                    self.Fctrl_str_ver[ele] = f"{cluster_name}.{module_name}.{func_name}" 
        except:
            ans = self.quantum_device.elements()
            eyeson_print("Your Hcfg didn't assign the flux connections so the Fctrl will be empty! ")
            for q in ans:
               self.Fctrl_str_ver[q] = f"pass" 
              

    def activate_str_Fctrl(self,cluster:Cluster):
        """ From string translate to attributes, made callable Fctl """
        Fctrl_active:callable = {}

        def pass_func(*arg):
            pass
        
        for q in self.Fctrl_str_ver:
            if self.Fctrl_str_ver[q] != "pass":
                attr = cluster
                for i in range(1,len(self.Fctrl_str_ver[q].split("."))):
                    attr = getattr(attr,self.Fctrl_str_ver[q].split(".")[i])
                Fctrl_active[q] = attr
            else:
                Fctrl_active[q] = pass_func

        return Fctrl_active


    def memo_refIQ(self,ref_dict:dict):
        """
        Memorize the reference IQ according to the given ref_dict, which the key named in "q0"..., and the value is composed in list by IQ values.\n
        Ex. ref_dict={"q0":[0.03,-0.004],...} 
        """
        for q in ref_dict:
            self.refIQ[q] = ref_dict[q]

    def memo_rotate_angle(self,angle_dict:dict):
       """
        Memorize the rotating angle according to the given angle_dict, which the key named in "q0"..., and the value is the angle in degree.\n
        Ex. angle_dict={"q0":75.3, ...} 
        """ 
       for q in angle_dict:
           self.rotate_angle[q] = angle_dict[q]
    
    def refresh_log(self,message:str):
        """
        Leave the message for this file.
        """
        self.Log = message

    def QD_loader(self, new_Hcfg:dict=None):
        """
        Load the QuantumDevice, Bias config, hardware config and Flux control callable dict from a given json file path contain the serialized QD.
        """
        update:bool = False
        with open(self.path, 'rb') as inp:
            gift:QDmanager = pickle.load(inp) # refer to `merged_file` in QD_keeper()


        try:  
            manager_ver = gift.manager_version
            if float(manager_ver.split("v")[-1]) < 2.0:
                update = True   
        except:
            update = True
        
        if update:
            self.version_converter(gift)
            print("This QD_file is out-updated, successfully updated !")

        else:
            # class
            self.Fluxmanager = gift.Fluxmanager
            self.q_num:int = len(list(filter(ret_q,self.Fluxmanager.get_bias_dict())))
            self.c_num:int = len(list(filter(ret_c,self.Fluxmanager.get_bias_dict())))
            # the notebook needa active from the old one to avoid some new items didn't be initialize, like Ec, ...
            self.Notewriter: Notebook = Notebook(q_number=self.q_num)
            
            self.Notewriter.activate_from_dict(gift.Notewriter.get_notebook())
            
            self.Waveformer = gift.Waveformer
            self.quantum_device = gift.quantum_device
            try:
                if manager_ver.lower() in ["v2.1", "v2.2"]:
                    self.StateDiscriminator = gift.StateDiscriminator
                else:
                    print("New Statifier generated ... ")
                    self.StateDiscriminator:Statifier = Statifier()
            except:
                print("Generating Statifier ...")
                self.StateDiscriminator:Statifier = Statifier()

            try:
                self.activeReset = gift.activeReset
            except:
                pass
            # string/ int
            self.manager_version = gift.manager_version
            self.chip_name:str = gift.chip_name
            self.chip_type:str = gift.chip_type
            self.Identity:str = gift.Identity
            self.Log:str = gift.Log
            self.Fctrl_str_ver = gift.Fctrl_str_ver
            self.machine_IP:str = gift.machine_IP
            
            
            # dict
            self.refIQ = gift.refIQ
            self.Hcfg = gift.Hcfg
            self.rotate_angle = gift.rotate_angle
            
            if new_Hcfg is not None:
                from qblox_drive_AS.support.UserFriend import slightly_print
                
                # inherit old RO LO freq
                old_ro_lo = [self.Hcfg["hardware_options"]["modulation_frequencies"][i]["lo_freq"] for i in self.Hcfg["hardware_options"]["modulation_frequencies"] if i.split(":")[-1].split("-")[0]=='res'][0]
                for i in new_Hcfg["hardware_options"]["modulation_frequencies"]:
                    if i.split(":")[-1].split("-")[0] == 'res':
                        new_Hcfg["hardware_options"]["modulation_frequencies"][i]["lo_freq"] = old_ro_lo
                
                self.Hcfg = new_Hcfg
                self.quantum_device.hardware_config(new_Hcfg)
                slightly_print("Saved new given Hardware config.")
                self.made_mobileFctrl()
            else:
                self.quantum_device.hardware_config(self.Hcfg)
        
        print("Old friends loaded!")

        
    def QD_keeper(self, special_path:str=''):
        """
        Save the merged dictionary to a json file with the given path. \n
        Ex. merged_file = {"QD":self.quantum_device,"Flux":self.Fluxmanager.get_bias_dict(),"Hcfg":Hcfg,"refIQ":self.refIQ,"Log":self.Log}
        """
        if self.path == '':
            if os.path.split(os.path.split(self.path)[0])[-1].split("_")[-1] != Data_manager().get_date_today():
                db = Data_manager()
                db.build_folder_today()
                self.path = os.path.join(db.raw_folder,f"{self.Identity}_SumInfo.pkl")
        
        with open(self.path if special_path == '' else special_path, 'wb') as file:
            pickle.dump(self, file)
            print(f'Summarized info had successfully saved to the given path!')

    def version_converter(self, gift):
        from qcat.analysis.state_discrimination.readout_fidelity import GMMROFidelity
        # string and int
        self.chip_name:str = gift["chip_info"]["name"]
        self.chip_type:str = gift["chip_info"]["type"]
        self.Identity:str = gift["ID"]
        self.Log:str = gift["Log"]
        self.Fctrl_str_ver = gift["Fctrl_str"]
        self.machine_IP:str = gift["IP"]
        self.q_num:int = len(list(filter(ret_q,gift["Flux"])))
        self.c_num:int = len(list(filter(ret_c,gift["Flux"])))
        # class    
        self.Fluxmanager :FluxBiasDict = FluxBiasDict(qb_number=self.q_num,cp_number=self.c_num)
        self.Fluxmanager.activate_from_dict(gift["Flux"])
        self.Notewriter: Notebook = Notebook(q_number=self.q_num)
        self.Notewriter.activate_from_dict(gift["Note"])
        if "Waveform" in list(gift.keys()):
            self.Waveformer:GateGenesis = GateGenesis(q_num=0,c_num=0,log2super=gift["Waveform"])
        else:
            self.Waveformer:GateGenesis = GateGenesis(self.q_num,self.c_num)
        self.quantum_device :QuantumDevice = gift["QD"]

        if "Discriminator" in list(gift.keys()):
            if type(gift["Discriminator"]) != GMMROFidelity:
                self.StateDiscriminator = gift["Discriminator"]
            else:
                self.StateDiscriminator:Statifier = Statifier()
        else:
            self.StateDiscriminator:Statifier = Statifier()
        
        
        # dict
        self.Hcfg = gift["Hcfg"]
        self.refIQ:dict = gift["refIQ"]
        self.rotate_angle = gift["rota_angle"]
        
        self.quantum_device.hardware_config(self.Hcfg)


    def build_new_QD(self,qubit_number:int,coupler_number:int,Hcfg:dict,cluster_ip:str,dr_loc:str,chip_name:str='',chip_type:str=''):

        """
        Build up a new Quantum Device, here are something must be given about it:\n
        (1) qubit_number: how many qubits is in the chip.\n
        (2) Hcfg: the hardware configuration between chip and cluster.\n
        (3) cluster_ip: which cluster is connected. Ex, cluster_ip='192.168.1.171'\n
        (4) dr_loc: which dr is this chip installed. Ex, dr_loc='dr4'
        """
        print("Building up a new quantum device system....")
        self.q_num = qubit_number
        self.cp_num = coupler_number
        self.Hcfg = Hcfg
        
        self.chip_name = chip_name
        self.chip_type = chip_type
        self.register(cluster_ip_adress=cluster_ip,which_dr=dr_loc,chip_name=chip_name,chip_type=chip_type)
        
        self.Fluxmanager :FluxBiasDict = FluxBiasDict(self.q_num,self.cp_num)
        self.Notewriter: Notebook = Notebook(self.q_num)
        self.Waveformer:GateGenesis = GateGenesis(q_num=self.q_num,c_num=self.cp_num)
        self.StateDiscriminator:Statifier = Statifier()

        
        # for firmware v0.7.0
        from qcodes.instrument import find_or_create_instrument
        self.quantum_device = find_or_create_instrument(QuantumDevice, recreate=True, name=f"QPU{dr_loc.lower()}")
        self.quantum_device.hardware_config(self.Hcfg)
        for qb_idx in range(self.q_num):
            self.rotate_angle[f"q{qb_idx}"] = [0]
            qubit = find_or_create_instrument(BasicTransmonElement, recreate=True, name=f"q{qb_idx}")
            qubit.measure.acq_channel(qb_idx)
            qubit.reset.duration(250e-6)
            qubit.clock_freqs.readout(6e9)
            qubit.measure.acq_delay(280e-9)
            qubit.measure.pulse_amp(0.5)
            qubit.measure.pulse_duration(1e-6+280e-9)
            qubit.measure.integration_time(1e-6)
            qubit.clock_freqs.f01(4e9)
            qubit.rxy.amp180(0.05)
            qubit.rxy.duration(40e-9)
            self.quantum_device.add_element(qubit)

        self.made_mobileFctrl()
        
    def keep_meas_option(self,target_q:str,z_bias:float,modi_idx:int):
        """ keep the following info into Notebook\n
        1) XY freq.\n
        2) RO freq.\n
        3) RO amp.\n
        4) pi-pulse amp.\n
        5) 2tone_pi amp.\n
        6) pi-pulse duration.\n
        7) ref-IQ point.\n
        8) bias of this point.\n
        9) ro attenuation.\n
        10) XY waveform info\n
        11) Z waveform info
        """
        print(z_bias)
        if modi_idx != "-1":
            if len(self.Notewriter.get_all_meas_options(target_q)) <= modi_idx:
                self.Notewriter.create_meas_options(target_q)
        qubit = self.quantum_device.get_element(target_q)
        ROF = qubit.clock_freqs.readout()
        XYF = qubit.clock_freqs.f01()
        pi_amp = qubit.rxy.amp180()
        conti_pi_amp = self.Notewriter.get_2tone_piampFor(target_q)
        pi_dura = qubit.rxy.duration()
        ref_iq = self.refIQ[target_q]
        ro_attenuation = self.Notewriter.get_DigiAtteFor(target_q,'ro')
        ro_amp = qubit.measure.pulse_amp()
        xy_gate_lib = self.Waveformer.get_log()["xy"][target_q]
        z_gate_lib = self.Waveformer.get_log()["z"][target_q]
        option_dict = {"f01":XYF,"rof":ROF,"rop":ro_amp,"pi_amp":pi_amp,"2tone_pi_amp":conti_pi_amp,"pi_dura":pi_dura,"refIQ":ref_iq,"bias":z_bias,"ro_atte":ro_attenuation,"XY_waveform":xy_gate_lib,"Z_waveform":z_gate_lib,"state_discriminator":self.StateDiscriminator}

        self.Notewriter.write_meas_options({target_q:option_dict},modi_idx)
        print(f"Optional meas point had been recorded! @ Z~{round(z_bias,3)}")


    def write_with_meas_option(self,target_q:str,idx_chosen:str):
        """ call the following info into QuantumDevice, Fluxmanager, Notewriter, QDmanager\n
        1) XY freq.\n
        2) RO freq.\n
        3) RO amp.\n
        4) pi-pulse amp.\n
        5) 2tone_pi amp.\n
        6) pi-pulse duration.\n
        7) ref-IQ point.\n
        8) bias of this point.\n
        9) ro attenuation.\n
        10) XY waveform info\n
        11) Z waveform info
        """
        option_selected:dict = self.Notewriter.get_all_meas_options(target_q)[int(idx_chosen)]
        qubit = self.quantum_device.get_element(target_q)
        qubit.clock_freqs.readout(option_selected["rof"])
        qubit.clock_freqs.f01(option_selected["f01"])
        qubit.rxy.amp180(option_selected["pi_amp"])
        self.Notewriter.save_2tone_piamp_for(target_q,float(option_selected["2tone_pi_amp"]))
        qubit.rxy.duration(option_selected["pi_dura"])
        self.refIQ[target_q] = option_selected["refIQ"]
        self.Notewriter.save_DigiAtte_For(int(option_selected["ro_atte"]),target_q,'ro')
        qubit.measure.pulse_amp(option_selected["rop"])
        for mode in ["xy", "z"]:
            self.Waveformer.modi_all_info_for(target_q,option_selected[f"{mode.upper()}_waveform"],mode)

        if idx_chosen != '0':
            self.Fluxmanager.save_tuneawayBias_for('manual',target_q,option_selected["bias"])
            self.Fluxmanager.press_offsweetspot_button(target_q,True) # here is the only way to press this button
        else:
            self.Fluxmanager.save_sweetspotBias_for(target_q,option_selected["bias"])
            self.Fluxmanager.press_offsweetspot_button(target_q,False)

        if "state_discriminator" in option_selected:
            self.StateDiscriminator = option_selected["state_discriminator"]
        else:
            self.StateDiscriminator = Statifier()



    ### Convenient short cuts
# Object to manage data and pictures store.

class Data_manager:
    
    def __init__(self):
        from qblox_drive_AS.support.Path_Book import meas_raw_dir
        from qblox_drive_AS.support.Path_Book import qdevice_backup_dir
        if not os.path.isdir(qdevice_backup_dir):
            os.mkdir(qdevice_backup_dir) 
        self.QD_back_dir = qdevice_backup_dir
        if not os.path.isdir(meas_raw_dir):
            os.mkdir(meas_raw_dir) 
        self.raw_data_dir = meas_raw_dir
        self.raw_folder = None

    # generate time label for netCDF file name
    def get_time_now(self)->str:
        """
        Since we save the Xarray into netCDF, we use the current time to encode the file name.\n
        Ex: 19:23:34 return H19M23S34 
        """
        current_time = datetime.datetime.now()
        return f"H{current_time.hour:02d}M{current_time.minute:02d}S{current_time.second:02d}"
    
    def get_date_today(self)->str:
        current_time = datetime.datetime.now()
        return f"{current_time.year:02d}{current_time.month:02d}{current_time.day:02d}"

    # build the folder for the data today
    def build_folder_today(self,parent_path:str=''):
        """
        Build up and return the folder named by the current date in the parent path.\n
        Ex. parent_path='D:/Examples/'
        """ 
        if parent_path == '':
            parent_path = self.QD_back_dir
            

        folder = self.get_date_today()
        new_folder = os.path.join(parent_path, folder) 
        if not os.path.isdir(new_folder):
            os.mkdir(new_folder) 
            print(f"Folder {folder} had been created!")

        pic_folder = os.path.join(new_folder, "pic")
        if not os.path.isdir(pic_folder):
            os.mkdir(pic_folder) 
        
        self.raw_folder = new_folder
        self.pic_folder = pic_folder
    
    def build_tuid_folder(self, tuid:str, additional_name:str=None):
        if self.raw_folder is None:
            self.build_folder_today(self.raw_data_dir)
        
        tuid_folder_path = os.path.join(self.raw_folder,f"{tuid}" if additional_name is None else f"{tuid}-{additional_name}")
        if not os.path.isdir(tuid_folder_path):
            os.mkdir(tuid_folder_path) 
            print(f"TUID Folder created at:\n{tuid_folder_path}")

    def build_packs_folder(self,special_name:str=None)->str:
        if self.raw_folder is None:
            self.build_folder_today(self.raw_data_dir)
        
        if special_name is None:
            special_name = self.get_time_now()
        
        pack_path = os.path.join(self.raw_folder,special_name)
        os.makedirs(pack_path,exist_ok=True)

        return pack_path



    def save_raw_data(self,QD_agent:QDmanager,ds:Dataset,qb:str='q0',label:str=0,exp_type:str='CS', specific_dataFolder:str='', get_data_loc:bool=False):
        """
        If the arg `specific_dataFolder` was given, the raw nc will be saved into that given path. 
        """
        exp_timeLabel = self.get_time_now()
        self.build_folder_today(self.raw_data_dir)
        parent_dir = self.raw_folder if specific_dataFolder =='' else specific_dataFolder
        dr_loc = QD_agent.Identity.split("#")[0]
        if exp_type.lower() == 'cs':
            path = os.path.join(parent_dir,f"{dr_loc}{qb}_CavitySpectro_{exp_timeLabel}.nc")
            
        elif exp_type.lower() == 'pd':
            path = os.path.join(parent_dir,f"{dr_loc}{qb}_PowerCavity_{exp_timeLabel}.nc")
            
        elif exp_type.lower() == 'fd':
            path = os.path.join(parent_dir,f"{dr_loc}{qb}_FluxCavity_{exp_timeLabel}.nc")
            
        elif exp_type.lower() == 'ss':
            path = os.path.join(parent_dir,f"{dr_loc}{qb}_SingleShot({label})_{exp_timeLabel}.nc")
            
        elif exp_type.lower() == '2tone':
            path = os.path.join(parent_dir,f"{dr_loc}{qb}_2tone_{exp_timeLabel}.nc")
            
        elif exp_type.lower() == 'f2tone':
            path = os.path.join(parent_dir,f"{dr_loc}{qb}_Flux2tone_{exp_timeLabel}.nc")
            
        elif exp_type.lower() == 'powerrabi':
            path = os.path.join(parent_dir,f"{dr_loc}{qb}_powerRabi_{exp_timeLabel}.nc")
            
        elif exp_type.lower() == 'timerabi':
            path = os.path.join(parent_dir,f"{dr_loc}{qb}_timeRabi_{exp_timeLabel}.nc")
        
        elif exp_type.lower() == 'rabi':
            path = os.path.join(parent_dir,f"{dr_loc}{qb}_Rabi_{exp_timeLabel}.nc")
            
        elif exp_type.lower() == 'ramsey':
            path = os.path.join(parent_dir,f"{dr_loc}{qb}_ramsey_{exp_timeLabel}.nc")
            
        elif exp_type.lower() == 't1':
            path = os.path.join(parent_dir,f"{dr_loc}{qb}_T1({label})_{exp_timeLabel}.nc")
            
        elif exp_type.lower() == 't2':
            path = os.path.join(parent_dir,f"{dr_loc}{qb}_T2({label})_{exp_timeLabel}.nc")
            
        elif exp_type.lower() == 'rofcali':
            path = os.path.join(parent_dir,f"{dr_loc}{qb}_RofCali({label})_{exp_timeLabel}.nc")
            
        elif exp_type.lower() == 'zt1':
            path = os.path.join(parent_dir,f"{dr_loc}{qb}_zT1({label})_{exp_timeLabel}.nc")
            
        elif exp_type.lower() == 'xylcali':
            path = os.path.join(parent_dir,f"{dr_loc}{qb}_XYLCali({label})_{exp_timeLabel}.nc")
            
        elif exp_type.lower() == 'xyl05cali':
            path = os.path.join(parent_dir,f"{dr_loc}{qb}_HalfPiCali({label})_{exp_timeLabel}.nc")
            
        elif exp_type.lower()[:4] == 'cryo':
            path = os.path.join(parent_dir,f"{dr_loc}{qb}_CryoScope{exp_type.lower()[-1]}({label})_{exp_timeLabel}.nc")
            
        elif exp_type.lower() == 'chevron':
            path = os.path.join(parent_dir,f"{dr_loc}{qb}_RabiChevron_{exp_timeLabel}.nc")
            
        elif exp_type.lower() == 'fringe':
            path = os.path.join(parent_dir,f"{dr_loc}{qb}RamseyFringe{exp_timeLabel}.nc")
            
        else:
            path = os.path.join(parent_dir,"Unknown.nc")
            raise KeyError("Wrong experience type!")
        
        ds.to_netcdf(path)

        if get_data_loc:
            return path
    
    def save_2Qraw_data(self,QD_agent:QDmanager,ds:Dataset,qubits:list,label:str=0,exp_type:str='iswap', specific_dataFolder:str='', get_data_loc:bool=False):
        exp_timeLabel = self.get_time_now()
        self.build_folder_today(self.raw_data_dir)
        parent_dir = self.raw_folder if specific_dataFolder =='' else specific_dataFolder
        dr_loc = QD_agent.Identity.split("#")[0]
        
        operators = ""
        for qORc in qubits:
            operators += qORc

        if exp_type.lower() == 'iswap':
            path = os.path.join(parent_dir,f"{dr_loc}{operators}_iSwap_{exp_timeLabel}.nc")
            ds.to_netcdf(path)
        else:
            path = None
            raise KeyError(f"irrecognizable 2Q gate exp = {exp_type}")
        
        if get_data_loc:
            return path
        
    
    def save_histo_pic(self,QD_agent:QDmanager,hist_dict:dict,qb:str='q0',mode:str="t1", show_fig:bool=False, save_fig:bool=True,pic_folder:str=''):
        from qblox_drive_AS.support.Pulse_schedule_library import hist_plot
        if QD_agent is not None:
            dr_loc = QD_agent.Identity.split("#")[0]
        else:
            dr_loc = "DR-"
        exp_timeLabel = self.get_time_now()
        if pic_folder == '':
            self.build_folder_today(self.raw_data_dir)
            pic_dir = self.pic_folder
        else:
            pic_dir = pic_folder
        
        if mode.lower() =="t1" :
            if save_fig:
                fig_path = os.path.join(pic_dir,f"{dr_loc}{qb}_T1histo_{exp_timeLabel}.png")
            else:
                fig_path = ''
            hist_plot(qb,hist_dict ,title=f"T1",save_path=fig_path, show=show_fig)
        elif mode.lower() =="t2*" :
            if save_fig:
                fig_path = os.path.join(pic_dir,f"{dr_loc}{qb}_T2histo_{exp_timeLabel}.png")
            else:
                fig_path = ''
            hist_plot(qb,hist_dict ,title=f"T2*",save_path=fig_path, show=show_fig)
        elif mode.lower() =="t2" :
            if save_fig:
                fig_path = os.path.join(pic_dir,f"{dr_loc}{qb}_T2ehisto_{exp_timeLabel}.png")
            else:
                fig_path = ''
            hist_plot(qb,hist_dict ,title=f"T2",save_path=fig_path, show=show_fig)
        elif mode.lower() in ["ss", "os"] :
            if save_fig:
                fig_path = os.path.join(pic_dir,f"{dr_loc}{qb}_effThisto_{exp_timeLabel}.png")
            else:
                fig_path = ''
            hist_plot(qb,hist_dict ,title=f"eff_T",save_path=fig_path, show=show_fig)
        elif mode.lower() in ["pop"] :
            if save_fig:
                fig_path = os.path.join(pic_dir,f"{dr_loc}{qb}_thermalPOPhisto_{exp_timeLabel}.png")
            else:
                fig_path = ''
            hist_plot(qb,hist_dict ,title=f"ThermalPop",save_path=fig_path, show=show_fig)
        else:
            raise KeyError("mode should be 'T1' or 'T2'!")
        
    def save_multiplex_pics(self, QD_agent:QDmanager, qb:str, exp_type:str, fig:Figure, specific_dataFolder:str=''):
        exp_timeLabel = self.get_time_now()
        self.build_folder_today(self.raw_data_dir)
        multiplex_ro_dir = os.path.join(self.raw_folder, "MultiplexingRO")
        if not os.path.exists(multiplex_ro_dir):
            os.mkdir(multiplex_ro_dir)
        parent_dir = multiplex_ro_dir if specific_dataFolder =='' else specific_dataFolder
        if QD_agent != None:
            dr_loc = QD_agent.Identity.split("#")[0]
        else:
            dr_loc = "ARBi"
        if exp_type.lower() == 'cs':
            path = os.path.join(parent_dir,f"{dr_loc}{qb}_MultiplexCS_{exp_timeLabel}.png")
        else:
            raise KeyError(f"Un-supported exp-type was given = {exp_type}")
        fig.savefig(path)
        plt.close()
    
    def save_dict2json(self,QD_agent:QDmanager,data_dict:dict,qb:str='q0',get_json:bool=False):
        """
        Save a dict into json file. Currently ONLY support z-gate 2tone fitting data.
        """
        import json
        exp_timeLabel = self.get_time_now()
        self.build_folder_today(self.raw_data_dir)
        dr_loc = QD_agent.Identity.split("#")[0]
        path = os.path.join(self.raw_folder,f"{dr_loc}{qb}_FluxFqFIT_{exp_timeLabel}.json")
        with open(path, "w") as json_file:
            json.dump(data_dict, json_file)
        print("Flux vs fq to-fit data had been saved!")
        if get_json:
            return path
    
    def get_today_picFolder(self)->str:
        """
        Get the picture folder today. Return its path.
        """
        self.build_folder_today(self.raw_data_dir)
        return self.pic_folder
    
    def creat_datafolder_today(self,folder_name:str)->str:
        """ create a new folder in the raw data folder today with the given name"""
        self.build_folder_today(self.raw_data_dir)
        new_folder = os.path.join(self.raw_folder,folder_name)
        if not os.path.exists(new_folder):
            os.mkdir(new_folder)
        return new_folder


if __name__ == "__main__":
    QD = QDmanager("qblox_drive_AS/QD_backup/20250508/DR1#11_SumInfo.pkl")
    QD.QD_loader()
    QD.retrieve_complete_HCFG()


