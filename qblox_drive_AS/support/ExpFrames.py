from numpy import ndarray
from abc import ABC
import traceback, os
from datetime import datetime
from xarray import DataArray
from qblox_drive_AS.support.QDmanager import QDmanager, Data_manager, BasicTransmonElement
from qblox_drive_AS.analysis.Multiplexing_analysis import Multiplex_analyzer
from qblox_drive_AS.support.UserFriend import *
from xarray import open_dataset
from numpy import array, linspace, logspace, median, std
from abc import abstractmethod
from qblox_drive_AS.support import init_meas, init_system_atte, shut_down, coupler_zctrl, advise_where_fq, set_LO_frequency, ReadoutFidelity_acq_analyzer, check_OS_model_ready, sort_dict_with_qidx
from qblox_drive_AS.support.Pulse_schedule_library import QS_fit_analysis
from qblox_drive_AS.analysis.raw_data_demolisher import ZgateT1_dataReducer



class ExpGovernment(ABC):
    def __init__(self):
        self.QD_path:str = ""
        self.save_pics:bool = True
        self.keep_QD:bool = True
        self.save_OS_model:bool = True

        self.sum_dict = {}
    
    @abstractmethod
    def SetParameters(self,*args,**kwargs):
        pass

    @abstractmethod
    def PrepareHardware(self,*args,**kwargs):
        pass

    @abstractmethod
    def RunMeasurement(self,*args,**kwargs):
        pass

    @abstractmethod
    def RunAnalysis(self,*args,**kwargs):
        pass

    @abstractmethod
    def CloseMeasurement(self,*args,**kwargs):
        pass

    @abstractmethod
    def WorkFlow(self):
        pass



class BroadBand_CavitySearching(ExpGovernment):
    def __init__(self,QD_path:str,data_folder:str=None,JOBID:str=None):
        super().__init__()
        self.QD_path = QD_path
        self.save_dir = data_folder
        self.__raw_data_location:str = ""
        self.JOBID = JOBID

    @property
    def RawDataPath(self):
        return self.__raw_data_location

    def SetParameters(self, freq_start:float, freq_end:float, freq_pts:float, res_name:list=['q0']):
        self.target_qs = res_name
        self.freq_start = freq_start
        self.freq_end = freq_end
        self.freq_pts = freq_pts
    
    def PrepareHardware(self):
        self.QD_agent, self.cluster, self.meas_ctrl, self.ic, self.Fctrl = init_meas(QuantumDevice_path=self.QD_path)
        hcfg = self.QD_agent.quantum_device.hardware_config()
        # Set the system attenuations
        
        for q in self.target_qs:
            init_system_atte(self.QD_agent.quantum_device,[q],ro_out_att=self.QD_agent.Notewriter.get_DigiAtteFor(q, 'ro'))
        # Readout select
        self.qrmRF_slot_idx = []

        for port_loc, port_name in hcfg["connectivity"]["graph"]:
            for q in self.target_qs:
                if port_name == f'{q}:res':
                    if int(port_loc.split(".")[1][6:]) not in self.qrmRF_slot_idx:
                        self.qrmRF_slot_idx.append(int(port_loc.split(".")[1][6:]))
        
        if len(self.qrmRF_slot_idx) == 0:
            raise ValueError("Can not search any QRM-RF module in your cluster, check it please !")
        
    
    def RunMeasurement(self):
        from qblox_drive_AS.SOP.wideCS import wideCS
        self.plot_item = {}
        for slot_idx in self.qrmRF_slot_idx:
            self.readout_module = self.cluster.modules[slot_idx-1]
            dataset = wideCS(self.readout_module,self.freq_start,self.freq_end,self.freq_pts)
            if self.save_dir is not None:
                self.save_path = os.path.join(self.save_dir,f"BroadBandCS_Slot{slot_idx}_{datetime.now().strftime('%Y%m%d%H%M%S') if self.JOBID is None else self.JOBID}")
                self.__raw_data_location = self.save_path + ".nc"
                dataset.to_netcdf(self.__raw_data_location)
                self.plot_item[self.__raw_data_location] = self.save_path+".png"
            else:
                self.save_fig_path = None
        
    def CloseMeasurement(self):
        shut_down(self.cluster,self.Fctrl)


    def RunAnalysis(self,new_QD_path:str=None,new_file_path:str=None):
        """ User callable analysis function pack """
        from qblox_drive_AS.SOP.wideCS import plot_S21
        if new_QD_path is None:
            QD_file = self.QD_path
        else:
            QD_file = new_QD_path

        if new_file_path is None:
            file_path = list(self.plot_item.keys())
            fig_path = list(self.plot_item.values())
        else:
            file_path = [new_file_path]
            fig_path = [os.path.join(os.path.split(new_file_path)[0],"S21.png")]

        QD_savior = QDmanager(QD_file)
        QD_savior.QD_loader()
        
        for idx, file in enumerate(file_path):
            ds = open_dataset(file)

            plot_S21(ds,fig_path[idx])
            ds.close()
        #QD_savior.QD_keeper()


    def WorkFlow(self):
        
        self.PrepareHardware()

        self.RunMeasurement()

        self.CloseMeasurement()


class Zoom_CavitySearching(ExpGovernment):
    """ Helps you get the **BARE** cavities. """
    def __init__(self,QD_path:str,data_folder:str=None,JOBID:str=None):
        super().__init__()
        self.QD_path = QD_path
        self.save_dir = data_folder
        self.__raw_data_location:str = ""
        self.JOBID = JOBID

    @property
    def RawDataPath(self):
        return self.__raw_data_location

    def SetParameters(self, freq_range:dict, freq_pts:int=100, avg_n:int=100, execution:bool=True):
        """ freq_range: {"q0":[freq_start, freq_end], ...}, sampling function use linspace """
        freq = {}
        for q in freq_range:
            freq[q] = linspace(freq_range[q][0], freq_range[q][1], freq_pts)

        self.freq_range = sort_dict_with_qidx(freq)
        self.avg_n = avg_n
        self.execution = execution
        self.target_qs = list(self.freq_range.keys())



    def PrepareHardware(self):
        self.QD_agent, self.cluster, self.meas_ctrl, self.ic, self.Fctrl = init_meas(QuantumDevice_path=self.QD_path)
        # Set the system attenuations
        init_system_atte(self.QD_agent.quantum_device,self.target_qs,ro_out_att=self.QD_agent.Notewriter.get_DigiAtteFor(self.target_qs[0], 'ro'))
        # check QRM output voltage
        for q in self.target_qs:
            if self.QD_agent.quantum_device.get_element(q).measure.pulse_amp() > 0.99/len(self.target_qs):
                print(f"{q} ro amp had been decreased !")
                self.QD_agent.quantum_device.get_element(q).measure.pulse_amp(0.98/len(self.target_qs))
    
    def RunMeasurement(self):
        from qblox_drive_AS.SOP.CavitySpec import QD_RO_init, CavitySearch
        QD_RO_init(self.QD_agent,self.freq_range)
        meas = CavitySearch()
        meas.ro_elements = self.freq_range
        meas.execution = self.execution
        meas.n_avg = self.avg_n
        meas.meas_ctrl = self.meas_ctrl
        meas.QD_agent = self.QD_agent
        meas.run()
        dataset = meas.dataset
        
        
        if self.execution:
            if self.save_dir is not None:
                self.save_path = os.path.join(self.save_dir,f"zoomCS_{datetime.now().strftime('%Y%m%d%H%M%S') if self.JOBID is None else self.JOBID}")
                self.__raw_data_location = self.save_path + ".nc"
                dataset.to_netcdf(self.__raw_data_location)
                
            else:
                self.save_fig_path = None
        
    def CloseMeasurement(self):
        shut_down(self.cluster,self.Fctrl)


    def RunAnalysis(self,new_QD_path:str=None,new_file_path:str=None):
        """ User callable analysis function pack """
        from qblox_drive_AS.SOP.CavitySpec import CS_ana
        if self.execution:
            if new_QD_path is None:
                QD_file = self.QD_path
            else:
                QD_file = new_QD_path

            if new_file_path is None:
                file_path = self.__raw_data_location
                fig_path = self.save_dir
            else:
                file_path = new_file_path
                fig_path = os.path.split(new_file_path)[0]

            QD_savior = QDmanager(QD_file)
            QD_savior.QD_loader()

            ds = open_dataset(file_path)

            CS_ana(QD_savior,ds,fig_path)
            ds.close()
            QD_savior.QD_keeper()


    def WorkFlow(self):
    
        self.PrepareHardware()

        self.RunMeasurement()
        
        self.CloseMeasurement()
        
class PowerCavity(ExpGovernment):
    def __init__(self,QD_path:str,data_folder:str=None,JOBID:str=None):
        super().__init__()
        self.QD_path = QD_path
        self.save_dir = data_folder
        self.__raw_data_location:str = ""
        self.JOBID = JOBID

    @property
    def RawDataPath(self):
        return self.__raw_data_location

    def SetParameters(self, freq_span_range:dict, roamp_range:list, freq_pts:int=100, avg_n:int=100, execution:bool=True):
        """ ### Args:
            * freq_span_range: {"q0":[freq_span_start, freq_span_end], ...}, sampling function use linspace\n
            * roamp_range: [amp_start, amp_end, pts]\n
            * roamp_sampling_func (str): 'linspace', 'arange', 'logspace'
        """
        self.freq_range = {}
        freq_span_range = sort_dict_with_qidx(freq_span_range)
        
        self.tempor_freq:list = [freq_span_range,freq_pts] # After QD loaded, use it to set self.freq_range

        self.avg_n = avg_n
        self.execution = execution
        self.target_qs = list(freq_span_range.keys())

        from numpy import arange
        if roamp_range[-1] % 2 != 0:
            raise ValueError("Step for attenuation must be even !")


        if roamp_range[1] <= 60:
            x = [roamp_range[0], roamp_range[1] + roamp_range[-1], roamp_range[-1]]
        else:
            x = [roamp_range[0], 60 + roamp_range[-1], roamp_range[-1]]
        self.roamp_samples = arange(*x)

        
        

    def PrepareHardware(self):
        self.QD_agent, self.cluster, self.meas_ctrl, self.ic, self.Fctrl = init_meas(QuantumDevice_path=self.QD_path)
        # Set the system attenuations
        init_system_atte(self.QD_agent.quantum_device,self.target_qs,ro_out_att=self.QD_agent.Notewriter.get_DigiAtteFor(self.target_qs[0], 'ro'))

    def RunMeasurement(self):
        from qblox_drive_AS.SOP.nPowCavSpec import  PowerDepCavityPS
        from qblox_drive_AS.SOP.CavitySpec import QD_RO_init
        
        # set self.freq_range
        self.ro_amp = 0.9/len(list(self.QD_agent.quantum_device.elements()))
        for q in self.tempor_freq[0]:
            bare = self.QD_agent.Notewriter.get_bareFreqFor(q)
            qubit:BasicTransmonElement = self.QD_agent.quantum_device.get_element(q)
            qubit.measure.pulse_amp(self.ro_amp)
            self.freq_range[q] = linspace(bare+self.tempor_freq[0][q][0],bare+self.tempor_freq[0][q][1],self.tempor_freq[1])
        
        QD_RO_init(self.QD_agent,self.freq_range)
        
        meas = PowerDepCavityPS()
        meas.ro_elements = self.freq_range
        meas.power_samples = self.roamp_samples
        meas.execution = self.execution
        meas.n_avg = self.avg_n
        meas.meas_ctrl = self.meas_ctrl
        meas.QD_agent = self.QD_agent
        meas.run_iteratively()
        dataset = meas.dataset
        
        if self.execution:
            if self.save_dir is not None:
                self.save_path = os.path.join(self.save_dir,f"PowerCavity_{datetime.now().strftime('%Y%m%d%H%M%S') if self.JOBID is None else self.JOBID}")
                self.__raw_data_location = self.save_path + ".nc"
                dataset.to_netcdf(self.__raw_data_location)
                
            else:
                self.save_fig_path = None
        
    def CloseMeasurement(self):
        shut_down(self.cluster,self.Fctrl)


    def RunAnalysis(self,new_QD_path:str=None,new_file_path:str=None):
        """ User callable analysis function pack """
        from qblox_drive_AS.SOP.nPowCavSpec import plot_powerCavity_S21
        if self.execution:
            if new_QD_path is None:
                QD_file = self.QD_path
            else:
                QD_file = new_QD_path

            if new_file_path is None:
                file_path = self.__raw_data_location
                fig_path = self.save_dir
            else:
                file_path = new_file_path
                fig_path = os.path.split(new_file_path)[0]

            QD_savior = QDmanager(QD_file)
            QD_savior.QD_loader()

            ds = open_dataset(file_path)

            rof = plot_powerCavity_S21(ds,QD_savior,fig_path)
            ds.close()

        for q in list(self.QD_agent.quantum_device.elements()):
            qubit:BasicTransmonElement = self.QD_agent.quantum_device.get_element(q)
            qubit.measure.pulse_amp(self.ro_amp)
        for q in rof:
            qubit:BasicTransmonElement = self.QD_agent.quantum_device.get_element(q)
            qubit.clock_freqs.readout(rof[q])
        QD_savior.QD_keeper()
        slightly_print("Please go 'manuall_QD_manage.py' setting the RO attenuation !")


    def WorkFlow(self):
    
        self.PrepareHardware()

        self.RunMeasurement()

        self.CloseMeasurement()      

class Dressed_CavitySearching(ExpGovernment):
    """ Helps you get the **Dressed** cavities. """
    def __init__(self,QD_path:str,data_folder:str=None,JOBID:str=None):
        super().__init__()
        self.QD_path = QD_path
        self.save_dir = data_folder
        self.__raw_data_location:str = ""
        self.JOBID = JOBID

    @property
    def RawDataPath(self):
        return self.__raw_data_location

    def SetParameters(self, freq_range:dict, freq_pts:int=100, avg_n:int=100, execution:bool=True):
        """ 
        ### Args:\n
        * freq_range: {"q0":[freq_start, freq_end], ...}, sampling function use linspace\n
        * ro_amp: {"q0":0.1, "q2":.... }
        """
        freq = {}
        for q in freq_range:
            freq[q] = linspace(freq_range[q][0], freq_range[q][1], freq_pts)
        self.freq_range = sort_dict_with_qidx(freq)
        
        self.avg_n = avg_n
        self.execution = execution
        self.target_qs = list(self.freq_range.keys())


    def PrepareHardware(self):
        self.QD_agent, self.cluster, self.meas_ctrl, self.ic, self.Fctrl = init_meas(QuantumDevice_path=self.QD_path)
        # Set the system attenuations
        init_system_atte(self.QD_agent.quantum_device,self.target_qs,ro_out_att=self.QD_agent.Notewriter.get_DigiAtteFor(self.target_qs[0], 'ro')) 
        
    
    def RunMeasurement(self):
        from qblox_drive_AS.SOP.CavitySpec import QD_RO_init, CavitySearch
        QD_RO_init(self.QD_agent,self.freq_range)
        
        meas = CavitySearch()
        meas.ro_elements = self.freq_range
        meas.execution = self.execution
        meas.n_avg = self.avg_n
        meas.meas_ctrl = self.meas_ctrl
        meas.QD_agent = self.QD_agent
        meas.run()
        dataset = meas.dataset
        
        if self.execution:
            if self.save_dir is not None:
                self.save_path = os.path.join(self.save_dir,f"dressedCS_{datetime.now().strftime('%Y%m%d%H%M%S') if self.JOBID is None else self.JOBID}")
                self.__raw_data_location = self.save_path + ".nc"
                dataset.to_netcdf(self.__raw_data_location)
                
            else:
                self.save_fig_path = None
        
    def CloseMeasurement(self):
        shut_down(self.cluster,self.Fctrl)


    def RunAnalysis(self,new_QD_path:str=None,new_file_path:str=None):
        """ User callable analysis function pack """
        from qblox_drive_AS.SOP.CavitySpec import CS_ana
        if self.execution:
            if new_QD_path is None:
                QD_file = self.QD_path
            else:
                QD_file = new_QD_path

            if new_file_path is None:
                file_path = self.__raw_data_location
                fig_path = self.save_dir
            else:
                file_path = new_file_path
                fig_path = os.path.split(new_file_path)[0]

            QD_savior = QDmanager(QD_file)
            QD_savior.QD_loader()

            ds = open_dataset(file_path)
            
            CS_ana(QD_savior,ds,fig_path,keep_bare=False)
            ds.close()
            QD_savior.QD_keeper()


    def WorkFlow(self):
    
        self.PrepareHardware()

        self.RunMeasurement()

        self.CloseMeasurement() 
        
class FluxCoupler(ExpGovernment):
    def __init__(self,QD_path:str,data_folder:str=None,JOBID:str=None):
        super().__init__()
        self.QD_path = QD_path
        self.save_dir = data_folder
        self.__raw_data_location:str = ""
        self.JOBID = JOBID

    @property
    def RawDataPath(self):
        return self.__raw_data_location

    def SetParameters(self, freq_span_range:dict, bias_elements:list, flux_range:list, flux_sampling_func:str, freq_pts:int=100, avg_n:int=100, execution:bool=True):
        """ ### Args:
            * freq_span_range: {"q0":[freq_span_start, freq_span_end], ...}, sampling function use linspace\n
            * bias_elements (list): ["c0", "c1",... ]\n
            * flux_range: [amp_start, amp_end, pts]\n
            * flux_sampling_func (str): 'linspace', 'arange', 'logspace'
        """
        self.freq_range = {}
        self.tempor_freq:list = [sort_dict_with_qidx(freq_span_range),freq_pts] # After QD loaded, use it to set self.freq_range
        self.bias_targets = bias_elements
        self.avg_n = avg_n
        self.execution = execution
        self.target_qs = list(freq_span_range.keys())
        if flux_sampling_func in ['linspace','logspace','arange']:
            sampling_func:callable = eval(flux_sampling_func)
        else:
            sampling_func:callable = linspace
        self.flux_samples = sampling_func(*flux_range)

    def PrepareHardware(self):
        self.QD_agent, self.cluster, self.meas_ctrl, self.ic, self.Fctrl = init_meas(QuantumDevice_path=self.QD_path)
        # Set the system attenuations
        init_system_atte(self.QD_agent.quantum_device,self.target_qs,ro_out_att=self.QD_agent.Notewriter.get_DigiAtteFor(self.target_qs[0], 'ro'))

        
    def RunMeasurement(self):
        from qblox_drive_AS.SOP.CouplerFluxSpec import FluxDepCouplerPS
        from qblox_drive_AS.SOP.CavitySpec import QD_RO_init
        # set self.freq_range
        for q in self.tempor_freq[0]:
            rof = self.QD_agent.quantum_device.get_element(q).clock_freqs.readout()
            self.freq_range[q] = linspace(rof+self.tempor_freq[0][q][0],rof+self.tempor_freq[0][q][1],self.tempor_freq[1])
        QD_RO_init(self.QD_agent,self.freq_range)
        
        meas = FluxDepCouplerPS()
        meas.ro_elements = self.freq_range
        meas.flux_samples = self.flux_samples
        meas.set_bias_elements = self.bias_targets
        meas.execution = self.execution
        meas.n_avg = self.avg_n
        meas.meas_ctrl = self.meas_ctrl
        meas.QD_agent = self.QD_agent
        meas.run()
        dataset = meas.dataset

        if self.execution:
            if self.save_dir is not None:
                self.save_path = os.path.join(self.save_dir,f"FluxCoupler_{datetime.now().strftime('%Y%m%d%H%M%S') if self.JOBID is None else self.JOBID}")
                self.__raw_data_location = self.save_path + ".nc"
                dataset.to_netcdf(self.__raw_data_location)
                
            else:
                self.save_fig_path = None
        
    def CloseMeasurement(self):
        shut_down(self.cluster,self.Fctrl)


    def RunAnalysis(self,new_QD_path:str=None,new_file_path:str=None):
        """ User callable analysis function pack """
        if self.execution:
            if new_QD_path is None:
                QD_file = self.QD_path
            else:
                QD_file = new_QD_path

            if new_file_path is None:
                file_path = self.__raw_data_location
                fig_path = self.save_dir
            else:
                file_path = new_file_path
                fig_path = os.path.split(new_file_path)[0]

            QD_savior = QDmanager(QD_file)
            QD_savior.QD_loader()

            ds = open_dataset(file_path)
            for var in ds.data_vars:
                ANA = Multiplex_analyzer("m5")
                if var.split("_")[-1] != 'freq':
                    ANA._import_data(ds,2)
                    ANA._start_analysis(var_name=var)
                    ANA._export_result(fig_path)
            ds.close()



    def WorkFlow(self):
    
        self.PrepareHardware()

        self.RunMeasurement()

        self.CloseMeasurement()          

class FluxCavity(ExpGovernment):
    def __init__(self,QD_path:str,data_folder:str=None,JOBID:str=None):
        super().__init__()
        self.QD_path = QD_path
        self.save_dir = data_folder
        self.__raw_data_location:str = ""
        self.JOBID = JOBID

    @property
    def RawDataPath(self):
        return self.__raw_data_location

    def SetParameters(self, freq_span_range:dict, flux_range:list, flux_sampling_func:str, freq_pts:int=100, avg_n:int=100, execution:bool=True):
        """ ### Args:
            * freq_span_range: {"q0":[freq_span_start, freq_span_end], ...}, sampling function use linspace\n
            * flux_range: [amp_start, amp_end, pts]\n
            * flux_sampling_func (str): 'linspace', 'arange', 'logspace'
        """
        self.freq_range = {}
        self.tempor_freq:list = [sort_dict_with_qidx(freq_span_range),freq_pts] # After QD loaded, use it to set self.freq_range
        self.avg_n = avg_n
        self.execution = execution
        self.target_qs = list(freq_span_range.keys())
        if flux_sampling_func in ['linspace','logspace','arange']:
            sampling_func:callable = eval(flux_sampling_func)
        else:
            sampling_func:callable = linspace
        self.flux_samples = sampling_func(*flux_range)

    def PrepareHardware(self):
        self.QD_agent, self.cluster, self.meas_ctrl, self.ic, self.Fctrl = init_meas(QuantumDevice_path=self.QD_path)
        # Set the system attenuations
        init_system_atte(self.QD_agent.quantum_device,self.target_qs,ro_out_att=self.QD_agent.Notewriter.get_DigiAtteFor(self.target_qs[0], 'ro'))
        # bias coupler
        self.Fctrl = coupler_zctrl(self.Fctrl,self.QD_agent.Fluxmanager.build_Cctrl_instructions([cp for cp in self.Fctrl if cp[0]=='c' or cp[:2]=='qc'],'i'))
        
    def RunMeasurement(self):
        from qblox_drive_AS.SOP.FluxCavSpec import FluxDepCavityPS
        from qblox_drive_AS.SOP.CavitySpec import QD_RO_init
        # set self.freq_range
        for q in self.tempor_freq[0]:
            rof = self.QD_agent.quantum_device.get_element(q).clock_freqs.readout()
            self.freq_range[q] = linspace(rof+self.tempor_freq[0][q][0],rof+self.tempor_freq[0][q][1],self.tempor_freq[1])
            
        QD_RO_init(self.QD_agent,self.freq_range)

        meas = FluxDepCavityPS()
        meas.ro_elements = self.freq_range
        meas.flux_samples = self.flux_samples
        meas.execution = self.execution
        meas.n_avg = self.avg_n
        meas.meas_ctrl = self.meas_ctrl
        meas.QD_agent = self.QD_agent
        meas.run()
        dataset = meas.dataset


        # dataset = FluxCav_spec(self.QD_agent,self.meas_ctrl,self.Fctrl,self.freq_range,self.flux_samples,self.avg_n,self.execution)
        if self.execution:
            if self.save_dir is not None:
                self.save_path = os.path.join(self.save_dir,f"FluxCavity_{datetime.now().strftime('%Y%m%d%H%M%S') if self.JOBID is None else self.JOBID}")
                self.__raw_data_location = self.save_path + ".nc"
                dataset.to_netcdf(self.__raw_data_location)
                
            else:
                self.save_fig_path = None
        
    def CloseMeasurement(self):
        shut_down(self.cluster,self.Fctrl)


    def RunAnalysis(self,new_QD_path:str=None,new_file_path:str=None):
        """ User callable analysis function pack """
        from qblox_drive_AS.SOP.FluxCavSpec import update_flux_info_in_results_for
        if self.execution:
            
            if new_QD_path is None:
                QD_file = self.QD_path
            else:
                QD_file = new_QD_path

            if new_file_path is None:
                file_path = self.__raw_data_location
                fig_path = self.save_dir
            else:
                file_path = new_file_path
                fig_path = os.path.split(new_file_path)[0]

            QD_savior = QDmanager(QD_file)
            QD_savior.QD_loader()

            ds = open_dataset(file_path)
            answer = {}
            for var in ds.data_vars:
                if str(var).split("_")[-1] != 'freq':
                    ANA = Multiplex_analyzer("m6")
                    ANA._import_data(ds,2)
                    ANA._start_analysis(var_name=var)
                    ANA._export_result(fig_path)
                    answer[var] = ANA.fit_packs
            ds.close()
            permi = mark_input(f"What qubit can be updated ? {list(answer.keys())}/ all/ no ").lower()
            if permi in list(answer.keys()):
                update_flux_info_in_results_for(QD_savior,permi,answer[permi])
                QD_savior.QD_keeper()
            elif permi in ["all",'y','yes']:
                for q in list(answer.keys()):
                    update_flux_info_in_results_for(QD_savior,q,answer[q])
                QD_savior.QD_keeper()
            else:
                print("Updating got denied ~")



    def WorkFlow(self):
    
        self.PrepareHardware()

        self.RunMeasurement()

        self.CloseMeasurement()   

class IQ_references(ExpGovernment):
    """ Helps you get the **Dressed** cavities. """
    def __init__(self,QD_path:str,data_folder:str=None,JOBID:str=None):
        super().__init__()
        self.QD_path = QD_path
        self.save_dir = data_folder
        self.__raw_data_location:str = ""
        self.JOBID = JOBID

    @property
    def RawDataPath(self):
        return self.__raw_data_location

    def SetParameters(self, ro_amp_factor:dict, shots:int=100, execution:bool=True):
        """ 
        ### Args:\n
        * ro_amp_factor: {"q0":1.2, "q2":.... }, new ro amp = ro_amp*ro_amp_factor
        """
        self.ask_save:bool = False
        self.ro_amp = sort_dict_with_qidx(ro_amp_factor)
        self.avg_n = shots
        self.execution = execution
        self.target_qs = list(self.ro_amp.keys())


    def PrepareHardware(self):
        self.QD_agent, self.cluster, self.meas_ctrl, self.ic, self.Fctrl = init_meas(QuantumDevice_path=self.QD_path)
        # Set the system attenuations
        init_system_atte(self.QD_agent.quantum_device,self.target_qs,ro_out_att=self.QD_agent.Notewriter.get_DigiAtteFor(self.target_qs[0], 'ro')) 
        # bias coupler
        self.Fctrl = coupler_zctrl(self.Fctrl,self.QD_agent.Fluxmanager.build_Cctrl_instructions([cp for cp in self.Fctrl if cp[0]=='c' or cp[:2]=='qc'],'i'))
        for q in self.ro_amp:
            self.Fctrl[q](float(self.QD_agent.Fluxmanager.get_proper_zbiasFor(target_q=q)))
    
    def RunMeasurement(self):
        from qblox_drive_AS.SOP.RefIQ import RefIQPS
        meas = RefIQPS()
        meas.ro_elements = self.ro_amp
        meas.execution = self.execution
        meas.n_avg = self.avg_n
        meas.meas_ctrl = self.meas_ctrl
        meas.QD_agent = self.QD_agent
        meas.run()
        dataset = meas.dataset

        if self.execution:
            if self.save_dir is not None:
                self.save_path = os.path.join(self.save_dir,f"IQref_{datetime.now().strftime('%Y%m%d%H%M%S') if self.JOBID is None else self.JOBID}")
                self.__raw_data_location = self.save_path + ".nc"
                dataset.to_netcdf(self.__raw_data_location)
            else:
                self.save_fig_path = None
        
    def CloseMeasurement(self):
        shut_down(self.cluster,self.Fctrl)


    def RunAnalysis(self,new_QD_path:str=None,new_file_path:str=None):
        """ User callable analysis function pack """
        from qblox_drive_AS.SOP.RefIQ import IQ_ref_ana
        if self.execution:
            if new_QD_path is None:
                QD_file = self.QD_path
            else:
                QD_file = new_QD_path

            if new_file_path is None:
                file_path = self.__raw_data_location
                fig_path = self.save_dir
            else:
                file_path = new_file_path
                fig_path = os.path.split(new_file_path)[0]

            QD_savior = QDmanager(QD_file)
            QD_savior.QD_loader()

            ds = open_dataset(file_path)
            
            answer = {}
            for q in ds.data_vars:
                answer[q] = IQ_ref_ana(ds,q,fig_path)
            ds.close()
            
            QD_savior.memo_refIQ(answer)
            QD_savior.QD_keeper()


    def WorkFlow(self):
    
        self.PrepareHardware()

        self.RunMeasurement()

        self.CloseMeasurement() 

class PowerConti2tone(ExpGovernment):
    def __init__(self,QD_path:str,data_folder:str=None,JOBID:str=None):
        super().__init__()
        self.QD_path = QD_path
        self.save_dir = data_folder
        self.__raw_data_location:str = ""
        self.JOBID = JOBID
        self.fit_half_f02:bool=False
    @property
    def RawDataPath(self):
        return self.__raw_data_location

    def SetParameters(self, freq_range:dict, xyl_range:list, xyl_sampling_func:str, freq_pts:int=100, avg_n:int=100, ro_xy_overlap:bool=False, execution:bool=True):
        """ ### Args:
            * freq_range: {"q0":[freq_start, freq_end], ...}, sampling function use linspace\n
                * if someone is 0 like {"q0":[0]}, system will calculate an advised value.
            * xyl_range: [amp_start, amp_end, pts], if only one value inside, we only use that value. \n
            * xyl_sampling_func (str): 'linspace', 'arange', 'logspace'
        """
        self.freq_range = {}
        self.overlap:bool = ro_xy_overlap
        self.f_pts = freq_pts
        for q in freq_range:
            if len(freq_range[q]) == 1 and freq_range[q][0] == 0:
                self.freq_range[q] = freq_range[q][0]
            else:
                self.freq_range[q] = linspace(freq_range[q][0],freq_range[q][1],freq_pts)
        self.freq_range = sort_dict_with_qidx(self.freq_range)
        self.avg_n = avg_n
        self.execution = execution
        self.target_qs = list(freq_range.keys())
        if xyl_sampling_func in ['linspace','logspace','arange']:
            sampling_func:callable = eval(xyl_sampling_func)
        else:
            sampling_func:callable = linspace
        if len(xyl_range) != 1:
            self.xyl_samples = list(sampling_func(*xyl_range))
        else:
            self.xyl_samples = list(xyl_range)

    def PrepareHardware(self):
        self.QD_agent, self.cluster, self.meas_ctrl, self.ic, self.Fctrl = init_meas(QuantumDevice_path=self.QD_path)
        # Set the system attenuations
        init_system_atte(self.QD_agent.quantum_device,self.target_qs,ro_out_att=self.QD_agent.Notewriter.get_DigiAtteFor(self.target_qs[0], 'ro'), xy_out_att=0)
        # bias coupler
        self.Fctrl = coupler_zctrl(self.Fctrl,self.QD_agent.Fluxmanager.build_Cctrl_instructions([cp for cp in self.Fctrl if cp[0]=='c' or cp[:2]=='qc'],'i'))
        # set driving LO and offset bias
        for q in self.freq_range:
            self.Fctrl[q](float(self.QD_agent.Fluxmanager.get_proper_zbiasFor(target_q=q)))
            if isinstance(self.freq_range[q],ndarray):
                print(f"{q} LO @ {max(self.freq_range[q])}")
                set_LO_frequency(self.QD_agent.quantum_device,q=q,module_type='drive',LO_frequency=max(self.freq_range[q]))
        
    def RunMeasurement(self):
        from qblox_drive_AS.SOP.Cnti2Tone import PowerDepQubitPS
        # set self.freq_range
        for q in self.freq_range:
            if not isinstance(self.freq_range[q],ndarray):
                advised_fq = advise_where_fq(self.QD_agent,q,self.QD_agent.Notewriter.get_sweetGFor(q)) 
                eyeson_print(f"fq advice for {q} @ {round(advised_fq*1e-9,4)} GHz")
                IF_minus = self.QD_agent.Notewriter.get_xyIFFor(q)
                if advised_fq-IF_minus < 2e9:
                    raise ValueError(f"Attempting to set {q} driving LO @ {round((advised_fq-IF_minus)*1e-9,1)} GHz")
                set_LO_frequency(self.QD_agent.quantum_device,q=q,module_type='drive',LO_frequency=advised_fq-IF_minus)
                self.freq_range[q] = linspace(advised_fq-IF_minus-500e6,advised_fq-IF_minus,self.f_pts)

        meas = PowerDepQubitPS()
        meas.ro_elements = self.freq_range
        meas.power_samples = array(self.xyl_samples)
        meas.overlap = self.overlap
        meas.execution = self.execution
        meas.n_avg = self.avg_n
        meas.meas_ctrl = self.meas_ctrl
        meas.QD_agent = self.QD_agent
        meas.run()
        dataset = meas.dataset

        if self.execution:
            if self.save_dir is not None:
                if not self.fit_half_f02:
                    self.save_path = os.path.join(self.save_dir,f"PowerCnti2tone_{datetime.now().strftime('%Y%m%d%H%M%S') if self.JOBID is None else self.JOBID}")
                else:
                    self.save_path = os.path.join(self.save_dir,f"f02Half_{datetime.now().strftime('%Y%m%d%H%M%S') if self.JOBID is None else self.JOBID}")
                
                self.__raw_data_location = self.save_path + ".nc"
                dataset.to_netcdf(self.__raw_data_location)
                
            else:
                self.save_fig_path = None
        
    def CloseMeasurement(self):
        shut_down(self.cluster,self.Fctrl)

    def RunAnalysis(self,new_QD_path:str=None,new_file_path:str=None):
        """ User callable analysis function pack """
        from qblox_drive_AS.SOP.Cnti2Tone import update_2toneResults_for
        if self.execution:
            if new_QD_path is None:
                QD_file = self.QD_path
            else:
                QD_file = new_QD_path

            if new_file_path is None:
                file_path = self.__raw_data_location
                fig_path = self.save_dir
            else:
                file_path = new_file_path
                fig_path = os.path.split(new_file_path)[0]

            QD_savior = QDmanager(QD_file)
            QD_savior.QD_loader()

            ds = open_dataset(file_path)
            for var in ds.data_vars:
                if str(var).split("_")[-1] != 'freq':
                    ANA = Multiplex_analyzer("m8")     
                    ANA._import_data(ds,2,QD_savior.refIQ[var],QS_fit_analysis)
                    ANA._start_analysis(var_name=var)
                    ANA._export_result(fig_path)
                    if ANA.fit_packs != {}:
                        analysis_result = QS_fit_analysis(ANA.fit_packs[var]["contrast"],f=ANA.fit_packs[var]["xyf_data"])
                        update_2toneResults_for(QD_savior,var,{str(var):analysis_result},ANA.xyl[0],self.fit_half_f02)
                        print(f"{var} f12 = {QD_savior.quantum_device.get_element(var).clock_freqs.f12()*1e-9} GHz")
            ds.close()
            QD_savior.QD_keeper()

    def WorkFlow(self):
    
        self.PrepareHardware()

        self.RunMeasurement()

        self.CloseMeasurement() 

class FluxQubit(ExpGovernment):
    def __init__(self,QD_path:str,data_folder:str=None,JOBID:str=None):
        super().__init__()
        self.QD_path = QD_path
        self.save_dir = data_folder
        self.__raw_data_location:str = ""
        self.JOBID = JOBID

    @property
    def RawDataPath(self):
        return self.__raw_data_location

    def SetParameters(self, freq_span_range:dict, bias_targets:list,z_amp_range:list, z_amp_sampling_func:str, freq_pts:int=100, avg_n:int=100, execution:bool=True):
        """ ### Args:
            * freq_span_range: {"q0":[freq_span_start, freq_span_end], ...}, sampling function use linspace\n
            * bias_targets: list, what qubit need to be bias, like ['q0', 'q1', ...]\n
            * z_amp_range: [amp_start, amp_end, pts]\n
            * z_amp_sampling_func (str): 'linspace', 'arange', 'logspace'
        """
        self.freq_range = {}
        self.bias_elements = bias_targets
        self.tempor_freq:list = [freq_span_range,freq_pts] # After QD loaded, use it to set self.freq_range
        self.avg_n = avg_n
        self.execution = execution
        self.target_qs = list(sort_dict_with_qidx(freq_span_range).keys())
        if z_amp_sampling_func in ['linspace','logspace','arange']:
            sampling_func:callable = eval(z_amp_sampling_func)
        else:
            sampling_func:callable = linspace
        self.z_amp_samples = sampling_func(*z_amp_range)

    def PrepareHardware(self):
        self.QD_agent, self.cluster, self.meas_ctrl, self.ic, self.Fctrl = init_meas(QuantumDevice_path=self.QD_path)
        # Set the system attenuations
        init_system_atte(self.QD_agent.quantum_device,self.target_qs,ro_out_att=self.QD_agent.Notewriter.get_DigiAtteFor(self.target_qs[0], 'ro'),xy_out_att=0)
        # bias coupler
        self.Fctrl = coupler_zctrl(self.Fctrl,self.QD_agent.Fluxmanager.build_Cctrl_instructions([cp for cp in self.Fctrl if cp[0]=='c' or cp[:2]=='qc'],'i'))
        # offset bias
        self.z_ref = {}
        for q in self.target_qs:
            self.z_ref[q] = float(self.QD_agent.Fluxmanager.get_proper_zbiasFor(target_q=q))
            self.Fctrl[q](self.z_ref[q])
        
    def RunMeasurement(self):
        from qblox_drive_AS.SOP.FluxQubit import FluxDepQubitPS
        
        # set self.freq_range
        for q in self.target_qs:
            xyf = self.QD_agent.quantum_device.get_element(q).clock_freqs.f01()
            if abs(self.tempor_freq[0][q][0]-self.tempor_freq[0][q][1]) >500e6:
                raise ValueError(f"Attempting to span over 500 MHz for driving on {q}")
            self.freq_range[q] = linspace(xyf+self.tempor_freq[0][q][0],xyf+self.tempor_freq[0][q][1],self.tempor_freq[1])
            set_LO_frequency(self.QD_agent.quantum_device,q=q,module_type='drive',LO_frequency=max(self.freq_range[q]))
        
        meas = FluxDepQubitPS()
        meas.ro_elements = self.freq_range
        meas.flux_samples = self.z_amp_samples
        meas.bias_elements = self.bias_elements
        meas.execution = self.execution
        meas.n_avg = self.avg_n
        meas.meas_ctrl = self.meas_ctrl
        meas.QD_agent = self.QD_agent
        meas.run()
        dataset = meas.dataset  
        # dataset = Zgate_two_tone_spec(self.QD_agent,self.meas_ctrl,self.freq_range,self.bias_elements,self.z_amp_samples,self.avg_n,self.execution)
        if self.execution:
            for q in self.z_ref:
                dataset.attrs[f"{q}_z_ref"] = self.z_ref[q]
            if self.save_dir is not None:
                self.save_path = os.path.join(self.save_dir,f"FluxQubit_{datetime.now().strftime('%Y%m%d%H%M%S') if self.JOBID is None else self.JOBID}")
                self.__raw_data_location = self.save_path + ".nc"
                dataset.to_netcdf(self.__raw_data_location)
                
            else:
                self.save_fig_path = None
        
    def CloseMeasurement(self):
        shut_down(self.cluster,self.Fctrl)


    def RunAnalysis(self,new_QD_path:str=None,new_file_path:str=None):
        """ User callable analysis function pack """
        from qblox_drive_AS.SOP.FluxQubit import update_by_fluxQubit
        if self.execution:
            if new_QD_path is None:
                QD_file = self.QD_path
            else:
                QD_file = new_QD_path

            if new_file_path is None:
                file_path = self.__raw_data_location
                fig_path = self.save_dir
            else:
                file_path = new_file_path
                fig_path = os.path.split(new_file_path)[0]

            QD_savior = QDmanager(QD_file)
            QD_savior.QD_loader()

            ds = open_dataset(file_path)
            answer = {}
            for var in ds.data_vars:
                if str(var).split("_")[-1] != 'freq':
                    ANA = Multiplex_analyzer("m9") 
                    ANA._import_data(ds,2,QD_savior.refIQ[var],QS_fit_analysis)
                    ANA._start_analysis(var_name=var)
                    ANA._export_result(fig_path)
                    if len(list(ANA.fit_packs.keys())) != 0: answer[var] = ANA.fit_packs        
            ds.close()
            permi = mark_input(f"What qubit can be updated ? {list(answer.keys())}/ all/ no :").lower()
            if permi in list(answer.keys()):
                update_by_fluxQubit(QD_savior,answer[q],q)
                QD_savior.QD_keeper()
            elif permi in ["all",'y','yes']:
                for q in list(answer.keys()):
                    update_by_fluxQubit(QD_savior,answer[q],q)
                QD_savior.QD_keeper()
            else:
                print("Updating got denied ~")



    def WorkFlow(self):
    
        self.PrepareHardware()

        self.RunMeasurement()

        self.CloseMeasurement()   

class PowerRabiOsci(ExpGovernment):
    def __init__(self,QD_path:str,data_folder:str=None,JOBID:str=None):
        super().__init__()
        self.QD_path = QD_path
        self.save_dir = data_folder
        self.__raw_data_location:str = ""
        self.JOBID = JOBID

    @property
    def RawDataPath(self):
        return self.__raw_data_location

    def SetParameters(self, pi_amp:dict, pi_amp_sampling_func:str, pi_amp_pts_or_step:float=100, avg_n:int=100, execution:bool=True, OSmode:bool=False):
        """ ### Args:
            * pi_amp: {"q0":[pi_amp_start, pi_amp_end], ...}\n
            * pi_amp_sampling_func (str): 'linspace', 'arange', 'logspace'\n
            * pi_amp_pts_or_step: Depends on what sampling func you use, `linspace` or `logspace` set pts, `arange` set step. 
        """
        if pi_amp_sampling_func in ['linspace','logspace','arange']:
            sampling_func:callable = eval(pi_amp_sampling_func)
        else:
            sampling_func:callable = linspace
        
        self.pi_amp_samples = {}
        for q in sort_dict_with_qidx(pi_amp):
            self.pi_amp_samples[q] = sampling_func(*pi_amp[q],pi_amp_pts_or_step)
            
        self.avg_n = avg_n
        self.execution = execution
        self.OSmode = OSmode
        self.target_qs = list(pi_amp.keys())

        # FPGA memory limit guard
        if self.OSmode:
            for q in self.pi_amp_samples:
                if self.avg_n * self.pi_amp_samples[q].shape[0] > 131000:
                    raise MemoryError(f"Due to Qblox FPGA memory limit, amp_pts * shots must be less than 131000. And you are trying to set {self.avg_n * self.pi_amp_samples[q].shape[0]} for {q}")

        
        

    def PrepareHardware(self):
        self.QD_agent, self.cluster, self.meas_ctrl, self.ic, self.Fctrl = init_meas(QuantumDevice_path=self.QD_path)
        # bias coupler
        self.Fctrl = coupler_zctrl(self.Fctrl,self.QD_agent.Fluxmanager.build_Cctrl_instructions([cp for cp in self.Fctrl if cp[0]=='c' or cp[:2]=='qc'],'i'))
        # offset bias, LO and driving atte
        self.pi_dura = {}
        if self.OSmode:
            check_OS_model_ready(self.QD_agent, self.target_qs)
        for q in self.target_qs:
            self.Fctrl[q](self.QD_agent.Fluxmanager.get_proper_zbiasFor(target_q=q))
            IF_minus = self.QD_agent.Notewriter.get_xyIFFor(q)
            xyf = self.QD_agent.quantum_device.get_element(q).clock_freqs.f01()
            set_LO_frequency(self.QD_agent.quantum_device,q=q,module_type='drive',LO_frequency=xyf-IF_minus)
            init_system_atte(self.QD_agent.quantum_device,[q],ro_out_att=self.QD_agent.Notewriter.get_DigiAtteFor(q, 'ro'), xy_out_att=self.QD_agent.Notewriter.get_DigiAtteFor(q,'xy'))
        
    def RunMeasurement(self):
        from qblox_drive_AS.SOP.RabiOsci import RabiPS

        meas = RabiPS()
        meas.execution = self.execution
        meas.set_samples = self.pi_amp_samples
        meas.set_RabiType = "power"
        meas.set_os_mode = self.OSmode
        meas.n_avg = self.avg_n
        meas.meas_ctrl = self.meas_ctrl
        meas.QD_agent = self.QD_agent
        
        meas.run()
        dataset = meas.dataset
    
        if self.execution:
            if self.save_dir is not None:
                self.save_path = os.path.join(self.save_dir,f"PowerRabi_{datetime.now().strftime('%Y%m%d%H%M%S') if self.JOBID is None else self.JOBID}")
                self.__raw_data_location = self.save_path + ".nc"
                dataset.to_netcdf(self.__raw_data_location)
                
            else:
                self.save_fig_path = None
        
    def CloseMeasurement(self):
        shut_down(self.cluster,self.Fctrl)


    def RunAnalysis(self,new_QDagent:QDmanager=None,new_QD_path:str=None,new_file_path:str=None):
        """ User callable analysis function pack """
        from qblox_drive_AS.SOP.RabiOsci import conditional_update_qubitInfo
        if self.execution:
            if new_QD_path is None:
                QD_file = self.QD_path
            else:
                QD_file = new_QD_path

            if new_file_path is None:
                file_path = self.__raw_data_location
                fig_path = self.save_dir
            else:
                file_path = new_file_path
                fig_path = os.path.split(new_file_path)[0]

            if new_QDagent is None:
                QD_savior = QDmanager(QD_file)
                QD_savior.QD_loader()
            else:
                QD_savior = new_QDagent

            ds = open_dataset(file_path)
            md = None

            for var in ds.data_vars:
                if str(var).split("_")[-1] != 'variable':
                    ANA = Multiplex_analyzer("m11")
                    if ds.attrs['method'].lower() == "shot":
                        md = QD_savior.StateDiscriminator.summon_discriminator(var)   
                    
                    ANA._import_data(ds,1,QD_savior.refIQ[var] if QD_savior.rotate_angle[var][0] == 0 else QD_savior.rotate_angle[var])
                    ANA._start_analysis(var_name=var, OSmodel=md)
                    ANA._export_result(fig_path)
                    conditional_update_qubitInfo(QD_savior,ANA.fit_packs,var)  

            ds.close()
            QD_savior.QD_keeper()
            



    def WorkFlow(self):
    
        self.PrepareHardware()

        self.RunMeasurement()

        self.CloseMeasurement()   

class TimeRabiOsci(ExpGovernment):
    def __init__(self,QD_path:str,data_folder:str=None,JOBID:str=None):
        super().__init__()
        self.QD_path = QD_path
        self.save_dir = data_folder
        self.__raw_data_location:str = ""
        self.JOBID = JOBID

    @property
    def RawDataPath(self):
        return self.__raw_data_location

    def SetParameters(self, pi_dura:dict, pi_dura_sampling_func:str, pi_dura_pts_or_step:float=100, avg_n:int=100, execution:bool=True, OSmode:bool=False):
        """ ### Args:
            * pi_amp: {"q0": pi-amp in V, ...}\n
            * pi_dura: {"q0":[pi_duration_start, pi_duration_end], ...}\n
            * pi_dura_sampling_func (str): 'linspace', 'arange', 'logspace'\n
            * pi_dura_pts_or_step: Depends on what sampling func you use, `linspace` or `logspace` set pts, `arange` set step. 
        """
        from qblox_drive_AS.SOP.RabiOsci import sort_elements_2_multiples_of
        if pi_dura_sampling_func in ['linspace','logspace','arange']:
            sampling_func:callable = eval(pi_dura_sampling_func)
        else:
            sampling_func:callable = linspace
        
        self.pi_dura_samples = {}
        for q in sort_dict_with_qidx(pi_dura):
            if min(pi_dura[q]) == 0: pi_dura[q] = [4e-9, max(pi_dura[q])]
            self.pi_dura_samples[q] = sort_elements_2_multiples_of(sampling_func(*pi_dura[q],pi_dura_pts_or_step)*1e9,1)*1e-9
            
        self.avg_n = avg_n
        self.execution = execution
        self.OSmode = OSmode
        self.target_qs = list(pi_dura.keys())
        

    def PrepareHardware(self):
        self.QD_agent, self.cluster, self.meas_ctrl, self.ic, self.Fctrl = init_meas(QuantumDevice_path=self.QD_path)
        if self.OSmode:
            check_OS_model_ready(self.QD_agent, self.target_qs)
        # bias coupler
        self.Fctrl = coupler_zctrl(self.Fctrl,self.QD_agent.Fluxmanager.build_Cctrl_instructions([cp for cp in self.Fctrl if cp[0]=='c' or cp[:2]=='qc'],'i'))
        # offset bias, LO and atte
        self.pi_amp = {}
        for q in self.target_qs:
            self.Fctrl[q](self.QD_agent.Fluxmanager.get_proper_zbiasFor(target_q=q))
            IF_minus = self.QD_agent.Notewriter.get_xyIFFor(q)
            xyf = self.QD_agent.quantum_device.get_element(q).clock_freqs.f01()
            set_LO_frequency(self.QD_agent.quantum_device,q=q,module_type='drive',LO_frequency=xyf-IF_minus)
            init_system_atte(self.QD_agent.quantum_device,[q],ro_out_att=self.QD_agent.Notewriter.get_DigiAtteFor(q, 'ro'), xy_out_att=self.QD_agent.Notewriter.get_DigiAtteFor(q,'xy'))
            # self.pi_amp[q] = self.QD_agent.quantum_device.get_element(q).rxy.amp180()
          
    def RunMeasurement(self):
        from qblox_drive_AS.SOP.RabiOsci import RabiPS

        meas = RabiPS()
        meas.set_samples = self.pi_dura_samples
        meas.set_RabiType = "time"
        meas.set_os_mode = self.OSmode
        meas.n_avg = self.avg_n
        meas.meas_ctrl = self.meas_ctrl
        meas.QD_agent = self.QD_agent
        meas.execution = self.execution
        
        meas.run()
        dataset = meas.dataset

        if self.execution:
            if self.save_dir is not None:
                self.save_path = os.path.join(self.save_dir,f"TimeRabi_{datetime.now().strftime('%Y%m%d%H%M%S') if self.JOBID is None else self.JOBID}")
                self.__raw_data_location = self.save_path + ".nc"
                dataset.to_netcdf(self.__raw_data_location)
                
            else:
                self.save_fig_path = None
        
    def CloseMeasurement(self):
        shut_down(self.cluster,self.Fctrl)


    def RunAnalysis(self,new_QDagent:QDmanager=None,new_QD_path:str=None,new_file_path:str=None):
        """ User callable analysis function pack """
        from qblox_drive_AS.SOP.RabiOsci import conditional_update_qubitInfo
        if self.execution:
            if new_QD_path is None:
                QD_file = self.QD_path
            else:
                QD_file = new_QD_path

            if new_file_path is None:
                file_path = self.__raw_data_location
                fig_path = self.save_dir
            else:
                file_path = new_file_path
                fig_path = os.path.split(new_file_path)[0]

            if new_QDagent is None:
                QD_savior = QDmanager(QD_file)
                QD_savior.QD_loader()
            else:
                QD_savior = new_QDagent

            ds = open_dataset(file_path)
            md = None
        
            for var in ds.data_vars:
                if str(var).split("_")[-1] != 'variable':
                    ANA = Multiplex_analyzer("m11")  
                    if ds.attrs['method'].lower() == "shot":
                        md = QD_savior.StateDiscriminator.summon_discriminator(var)    
                    ANA._import_data(ds,1,QD_savior.refIQ[var] if QD_savior.rotate_angle[var][0] == 0 else QD_savior.rotate_angle[var])
                    ANA._start_analysis(var_name=var, OSmodel=md)
                    ANA._export_result(fig_path)
                    conditional_update_qubitInfo(QD_savior,ANA.fit_packs,var)  
                    
            ds.close()
            # QD_savior.QD_keeper(new_QD_dir)
            



    def WorkFlow(self):
    
        self.PrepareHardware()

        self.RunMeasurement()

        self.CloseMeasurement()   


class nSingleShot(ExpGovernment):
    """ Helps you get the **Dressed** cavities. """
    def __init__(self,QD_path:str,data_folder:str=None,JOBID:str=None):
        super().__init__()
        self.QD_path = QD_path
        self.save_dir = data_folder
        self.__raw_data_location:str = ""
        self.JOBID = JOBID

    @property
    def RawDataPath(self):
        return self.__raw_data_location
    
    @RawDataPath.setter
    def RawDataPath(self,path:str):
        self.__raw_data_location = path

    def SetParameters(self, target_qs:list, histo_counts:int=1, shots:int=10000, execution:bool=True):
        """ 
        ### Args:\n
        * target_qs: list, like ["q0", "q1", ...]
        """
        self.use_time_label:bool = False
        self.avg_n = shots
        self.execution = execution
        self.target_qs = sort_dict_with_qidx(target_qs)
        self.histos = histo_counts
        self.counter:int = 0
        if self.histos > 1:
            self.use_time_label = True



    def PrepareHardware(self):
        self.QD_agent, self.cluster, self.meas_ctrl, self.ic, self.Fctrl = init_meas(QuantumDevice_path=self.QD_path)
        # bias coupler
        self.Fctrl = coupler_zctrl(self.Fctrl,self.QD_agent.Fluxmanager.build_Cctrl_instructions([cp for cp in self.Fctrl if cp[0]=='c' or cp[:2]=='qc'],'i'))
        # offset bias, LO and driving atte
        for q in self.target_qs:
            self.Fctrl[q](self.QD_agent.Fluxmanager.get_proper_zbiasFor(target_q=q))
            IF_minus = self.QD_agent.Notewriter.get_xyIFFor(q)
            xyf = self.QD_agent.quantum_device.get_element(q).clock_freqs.f01()
            set_LO_frequency(self.QD_agent.quantum_device,q=q,module_type='drive',LO_frequency=xyf-IF_minus)
            init_system_atte(self.QD_agent.quantum_device,[q],ro_out_att=self.QD_agent.Notewriter.get_DigiAtteFor(q, 'ro'), xy_out_att=self.QD_agent.Notewriter.get_DigiAtteFor(q,'xy'))
        
    
    def RunMeasurement(self):
        from qblox_drive_AS.SOP.SingleShot import ReadoutFidelityPS
        meas = ReadoutFidelityPS()
        meas.set_target_qs = self.target_qs
        meas.set_shots = self.avg_n
        meas.set_repeat = self.histos
        
        meas.meas_ctrl = self.meas_ctrl
        meas.QD_agent = self.QD_agent
        meas.execution = self.execution
        
        meas.run()
        dataset = meas.dataset

        
        if self.execution:
            if self.save_dir is not None:
                self.save_path = os.path.join(self.save_dir,f"SingleShot_{datetime.now().strftime('%Y%m%d%H%M%S') if (self.JOBID is None or self.use_time_label) else self.JOBID}")
                self.__raw_data_location = self.save_path + ".nc"
                dataset.to_netcdf(self.__raw_data_location)
            else:
                self.save_fig_path = None
        
    def CloseMeasurement(self):
        shut_down(self.cluster,self.Fctrl)


    def RunAnalysis(self,new_QD_path:str=None,new_file_path:str=None,new_QDagent:QDmanager=None,new_pic_save_place:str=None):
        """ if histo_ana, it will check all the data in the same folder with the given new_file_path """

        if self.execution:
            if new_QD_path is None:
                QD_file = self.QD_path
            else:
                QD_file = new_QD_path

            if new_file_path is None:
                file_path = self.__raw_data_location
                fig_path = self.save_dir
            else:
                file_path = new_file_path
                fig_path = os.path.split(new_file_path)[0]

            if new_pic_save_place is not None:
                fig_path = new_pic_save_place

            if new_QDagent is None:
                QD_savior = QDmanager(QD_file)
                QD_savior.QD_loader()
            else:
                QD_savior = new_QDagent

            parent_dir = os.path.dirname(file_path)  # Get the parent directory
            date_part = os.path.basename(os.path.dirname(parent_dir))  # "20250122"
            time_part = os.path.basename(parent_dir) 
            ds = open_dataset(file_path)
            
            if self.histos == 1:
                for var in ds.data_vars:
                    try:
                        self.ANA = Multiplex_analyzer("m14")
                        pic_path = os.path.join(fig_path,f"{var}_SingleShot_{datetime.now().strftime('%Y%m%d%H%M%S') if self.JOBID is None else self.JOBID}")
                        self.ANA._import_data(ds[var]*1000,var_dimension=0,fq_Hz=QD_savior.quantum_device.get_element(var).clock_freqs.f01())
                        self.ANA._start_analysis(var_name=var)
                        if self.save_pics:
                            self.ANA._export_result(pic_path)

                        
                        if self.save_OS_model:
                            QD_savior.StateDiscriminator.serialize(var,self.ANA.gmm2d_fidelity, version=f"{date_part}_{time_part}") # will be in the future
                            da = DataArray(array(ds[var])[0]*1000, coords= [("mixer",array(["I","Q"])), ("prepared_state",array(ds.coords["prepared_state"])), ("index",array(ds.coords["index"]))] )
                            QD_savior.StateDiscriminator.check_model_alive(da, var, show_plot=False)
                        
                        self.sum_dict[var] = self.ANA.fit_packs

                        QD_savior.rotate_angle[var] = self.ANA.fit_packs["RO_rotation_angle"]
                    
                    except BaseException as err:
                        print(f"Get error while analyze your one-shot data: {err}")
                        traceback.print_exc()
                        eyeson_print("Trying to plot the raw data now... ")
                        self.ANA = Multiplex_analyzer("m14b")
                        self.ANA._import_data(ds[var]*1000,var_dimension=0)
                        pic_path = os.path.join(fig_path,f"{var}_SingleShot_{datetime.now().strftime('%Y%m%d%H%M%S') if self.JOBID is None else self.JOBID}.png")
                        if self.save_pics:
                            self.ANA._export_result(pic_path)
                        
                if self.save_OS_model:
                    QD_savior = ReadoutFidelity_acq_analyzer(QD_savior, ds)

                ds.close()
                if self.keep_QD:
                    QD_savior.QD_keeper()

            else:
                for var in ds.data_vars:
                    self.ANA = Multiplex_analyzer("m14")
                    self.ANA._import_data(ds[var]*1000,var_dimension=0,fq_Hz=QD_savior.quantum_device.get_element(var).clock_freqs.f01())
                    self.ANA._start_analysis(var_name=var)
                
                    highlight_print(f"{var}: {round(median(array(self.ANA.fit_packs['effT_mK'])),1)} +/- {round(std(array(self.ANA.fit_packs['effT_mK'])),1)} mK")
                    Data_manager().save_histo_pic(QD_savior,array(self.ANA.fit_packs["effT_mK"]),var,mode="ss",pic_folder=fig_path)
                    Data_manager().save_histo_pic(QD_savior,array(self.ANA.fit_packs["thermal_population"])*100,var,mode="pop",pic_folder=fig_path)

    def WorkFlow(self):
        
        self.PrepareHardware()

        self.RunMeasurement()

        self.CloseMeasurement() 



class Ramsey(ExpGovernment):
    def __init__(self,QD_path:str,data_folder:str=None,JOBID:str=None):
        super().__init__()
        self.QD_path = QD_path
        self.save_dir = data_folder
        self.__raw_data_location:str = ""
        self.JOBID = JOBID
        self.histos:int = 0
        self.sec_phase = 'x'

    @property
    def RawDataPath(self):
        return self.__raw_data_location

    def SetParameters(self, max_evo_time:float, target_qs:list, time_sampling_func:str, time_pts_or_step:int|float=100,histo_counts:int=1, avg_n:int=100, execution:bool=True, OSmode:bool=False)->None:
        """ ### Args:
            * max_evo_time: 100e-6\n
            * target_qs: ["q0", "q1", ...]
            * histo_counts: int, larger than 100 use while loop.\n
            * time_sampling_func (str): 'linspace', 'arange', 'logspace'\n
            * time_pts_or_step: Depends on what sampling func you use, `linspace` or `logspace` set pts, `arange` set step. 
        """
        from qblox_drive_AS.SOP.RabiOsci import sort_elements_2_multiples_of
        if time_sampling_func in ['linspace','logspace','arange']:
            sampling_func:callable = eval(time_sampling_func)
        else:
            raise ValueError(f"Can't recognize the given sampling function name = {time_sampling_func}")
        
        self.time_samples = {}
        if sampling_func in [linspace, logspace]:
            for q in sort_dict_with_qidx(target_qs):
                self.time_samples[q] = sort_elements_2_multiples_of(sampling_func(0, max_evo_time,time_pts_or_step)*1e9,1)*1e-9
        else:
            for q in sort_dict_with_qidx(target_qs): 
                self.time_samples[q] = sampling_func(0, max_evo_time,time_pts_or_step)

        self.avg_n = avg_n

        if histo_counts <= 100:
            self.want_while = False
            self.histos = histo_counts
        else:
            self.want_while = True
            self.histos = 1
        
        self.execution = execution
        self.OSmode = OSmode
        self.spin_num = {}
        self.target_qs = sort_dict_with_qidx(target_qs)
        
        # FPGA memory limit guard
        if self.OSmode:
            for q in self.time_samples:
                if self.avg_n * self.time_samples[q].shape[0] > 131000:
                    raise MemoryError(f"Due to Qblox FPGA memory limit, time_pts * shots must be less than 131000. And you are trying to set {self.avg_n * self.time_samples[q].shape[0]} for {q}")
        
        

    def PrepareHardware(self):
        self.QD_agent, self.cluster, self.meas_ctrl, self.ic, self.Fctrl = init_meas(QuantumDevice_path=self.QD_path)
        if self.OSmode:
            check_OS_model_ready(self.QD_agent, self.target_qs)
        # bias coupler
        self.Fctrl = coupler_zctrl(self.Fctrl,self.QD_agent.Fluxmanager.build_Cctrl_instructions([cp for cp in self.Fctrl if cp[0]=='c' or cp[:2]=='qc'],'i'))
        # offset bias, LO and atte
        for q in self.target_qs:
            self.Fctrl[q](self.QD_agent.Fluxmanager.get_proper_zbiasFor(target_q=q))
            IF_minus = self.QD_agent.Notewriter.get_xyIFFor(q)
            slightly_print(f"{q} arti-detune = {round(self.QD_agent.Notewriter.get_artiT2DetuneFor(q)*1e-6,2)} MHz")
            xyf = self.QD_agent.quantum_device.get_element(q).clock_freqs.f01()
            set_LO_frequency(self.QD_agent.quantum_device,q=q,module_type='drive',LO_frequency=xyf-IF_minus)
            init_system_atte(self.QD_agent.quantum_device,[q],ro_out_att=self.QD_agent.Notewriter.get_DigiAtteFor(q, 'ro'), xy_out_att=self.QD_agent.Notewriter.get_DigiAtteFor(q,'xy'))
        
    def RunMeasurement(self):
        from qblox_drive_AS.SOP.T2 import RamseyT2PS
        meas = RamseyT2PS()
        meas.set_time_samples = self.time_samples
        meas.set_os_mode = self.OSmode
        meas.enable_arti_detune = True
        meas.n_avg = self.avg_n
        meas.set_repeat = self.histos
        meas.set_spin_num = self.spin_num
        meas.set_second_phase = self.sec_phase
        meas.meas_ctrl = self.meas_ctrl
        meas.QD_agent = self.QD_agent
        meas.execution = self.execution
        
        meas.run()
        dataset = meas.dataset


        # dataset = Ramsey(self.QD_agent,self.meas_ctrl,self.time_samples,self.spin_num,self.histos,self.avg_n,self.execution)
        if self.execution:
            if self.save_dir is not None:
                self.save_path = os.path.join(self.save_dir,f"Ramsey_{datetime.now().strftime('%Y%m%d%H%M%S') if self.JOBID is None else self.JOBID}")
                self.__raw_data_location = self.save_path + ".nc"
                dataset.to_netcdf(self.__raw_data_location)
                
            else:
                self.save_fig_path = None
        
    def CloseMeasurement(self):
        shut_down(self.cluster,self.Fctrl)


    def RunAnalysis(self,new_QD_path:str=None,new_file_path:str=None,new_QDagent:QDmanager=None,new_pic_save_place:str=None):
        """ User callable analysis function pack """
        
        if self.execution:
            if new_QD_path is None:
                QD_file = self.QD_path
            else:
                QD_file = new_QD_path

            if new_file_path is None:
                file_path = self.__raw_data_location
                fig_path = self.save_dir
            else:
                file_path = new_file_path
                fig_path = os.path.split(new_file_path)[0]

            if new_QDagent is None:
                QD_savior = QDmanager(QD_file)
                QD_savior.QD_loader()
            else:
                QD_savior = new_QDagent

            if new_pic_save_place is not None:
                fig_path = new_pic_save_place

            ds = open_dataset(file_path)
            md = None
            self.corrected_detune = {}
            
            for var in ds.data_vars:
                if var.split("_")[-1] != 'x':
                    self.ANA = Multiplex_analyzer("m12")
                    if ds.attrs['method'].lower() == "shot":
                        md = QD_savior.StateDiscriminator.summon_discriminator(var)
                    if QD_savior.rotate_angle[var][0] != 0:
                        ref = QD_savior.rotate_angle[var]
                    else:
                        eyeson_print(f"{var} rotation angle is 0, use contrast to analyze.")
                        ref = QD_savior.refIQ[var]
                    self.ANA._import_data(ds,var_dimension=2,refIQ=ref)
                    self.ANA._start_analysis(var_name=var, OSmodel=md)
                    if self.save_pics:
                        self.ANA._export_result(fig_path)

                    if self.sec_phase.lower() == 'y':
                        if (self.ANA.fit_packs['phase'] % 360 + 360) % 360 > 180:
                            sign = -1
                        else:
                            sign = 1
                        
                        self.corrected_detune[var] = sign*self.ANA.fit_packs['freq']
                    self.ANA.fit_packs.update({"plot_item":self.ANA.plot_item})
                    self.sum_dict[var] = self.ANA.fit_packs
                    """ Storing """
                    if self.histos >= 50:
                        QD_savior.Notewriter.save_T2_for(self.ANA.fit_packs["median_T2"],var)
                   
            ds.close()
            if self.keep_QD:
                QD_savior.QD_keeper()
            

    def WorkFlow(self,freq_detune_Hz:float=None):
        while True:
            self.PrepareHardware()

            if freq_detune_Hz is not None:
                for q in self.target_qs:
                    self.QD_agent.quantum_device.get_element(q).clock_freqs.f01(self.QD_agent.quantum_device.get_element(q).clock_freqs.f01()+freq_detune_Hz)

            self.RunMeasurement()

            self.CloseMeasurement()   
            if not self.want_while:
                break

class SpinEcho(ExpGovernment):
    def __init__(self,QD_path:str,data_folder:str=None,JOBID:str=None):
        super().__init__()
        self.QD_path = QD_path
        self.save_dir = data_folder
        self.__raw_data_location:str = ""
        self.JOBID = JOBID

    @property
    def RawDataPath(self):
        return self.__raw_data_location

    def SetParameters(self, max_evo_time:float, target_qs:list, time_sampling_func:str, time_pts_or_step:int|float=100,histo_counts:int=1, avg_n:int=100, execution:bool=True, OSmode:bool=False)->None:
        """ ### Args:
            * max_evo_time: 100e-6\n
            * target_qs: ["q0", "q1", ...]
            * histo_counts: int, larger than 100 use while loop.\n
            * time_sampling_func (str): 'linspace', 'arange', 'logspace'\n
            * time_pts_or_step: Depends on what sampling func you use, `linspace` or `logspace` set pts, `arange` set step. 
        """
        from qblox_drive_AS.SOP.RabiOsci import sort_elements_2_multiples_of
        if time_sampling_func in ['linspace','logspace','arange']:
            sampling_func:callable = eval(time_sampling_func)
        else:
            raise ValueError(f"Can't recognize the given sampling function name = {time_sampling_func}")
        
        self.time_samples = {}
        self.spin_num = {}
        if sampling_func in [linspace, logspace]:
            for q in sort_dict_with_qidx(target_qs):
                self.time_samples[q] = sort_elements_2_multiples_of(sampling_func(0,max_evo_time,time_pts_or_step)*1e9,2)*1e-9
        else:
            for q in sort_dict_with_qidx(target_qs):
                self.time_samples[q] = sampling_func(0,max_evo_time,time_pts_or_step)

        self.avg_n = avg_n

        if histo_counts <= 100:
            self.want_while = False
            self.histos = histo_counts
        else:
            self.want_while = True
            self.histos = 1
        
        self.execution = execution
        self.OSmode = OSmode
        
        self.target_qs = sort_dict_with_qidx(target_qs)

        # FPGA memory limit guard
        if self.OSmode:
            for q in self.time_samples:
                if self.avg_n * self.time_samples[q].shape[0] > 131000:
                    raise MemoryError(f"Due to Qblox FPGA memory limit, time_pts * shots must be less than 131000. And you are trying to set {self.avg_n * self.time_samples[q].shape[0]} for {q}")
        
        

    def PrepareHardware(self):
        self.QD_agent, self.cluster, self.meas_ctrl, self.ic, self.Fctrl = init_meas(QuantumDevice_path=self.QD_path)
        if self.OSmode:
            check_OS_model_ready(self.QD_agent, self.target_qs)
        # bias coupler
        self.Fctrl = coupler_zctrl(self.Fctrl,self.QD_agent.Fluxmanager.build_Cctrl_instructions([cp for cp in self.Fctrl if cp[0]=='c' or cp[:2]=='qc'],'i'))
        # offset bias, LO and atte
        for q in self.target_qs:
            self.spin_num[q] = 1
            self.Fctrl[q](self.QD_agent.Fluxmanager.get_proper_zbiasFor(target_q=q))
            IF_minus = self.QD_agent.Notewriter.get_xyIFFor(q)
            xyf = self.QD_agent.quantum_device.get_element(q).clock_freqs.f01()
            set_LO_frequency(self.QD_agent.quantum_device,q=q,module_type='drive',LO_frequency=xyf-IF_minus)
            init_system_atte(self.QD_agent.quantum_device,[q],ro_out_att=self.QD_agent.Notewriter.get_DigiAtteFor(q, 'ro'), xy_out_att=self.QD_agent.Notewriter.get_DigiAtteFor(q,'xy'))
        
    def RunMeasurement(self):
        from qblox_drive_AS.SOP.T2 import RamseyT2PS
        meas = RamseyT2PS()
        meas.set_time_samples = self.time_samples
        meas.set_os_mode = self.OSmode
        meas.n_avg = self.avg_n
        meas.set_repeat = self.histos
        meas.set_spin_num = self.spin_num
        meas.set_second_phase = 'x'
        meas.meas_ctrl = self.meas_ctrl
        meas.QD_agent = self.QD_agent
        meas.execution = self.execution
        
        meas.run()
        dataset = meas.dataset
        # dataset = Ramsey(self.QD_agent,self.meas_ctrl,self.time_samples,self.spin_num,self.histos,self.avg_n,self.execution)
        if self.execution:
            if self.save_dir is not None:
                self.save_path = os.path.join(self.save_dir,f"SpinEcho_{datetime.now().strftime('%Y%m%d%H%M%S') if self.JOBID is None else self.JOBID}")
                self.__raw_data_location = self.save_path + ".nc"
                dataset.to_netcdf(self.__raw_data_location)
                
            else:
                self.save_fig_path = None
        
    def CloseMeasurement(self):
        shut_down(self.cluster,self.Fctrl)


    def RunAnalysis(self,new_QD_path:str=None,new_file_path:str=None,new_QDagent:QDmanager=None,new_pic_save_place:str=None):
        """ User callable analysis function pack """
        
        if self.execution:
            if new_QD_path is None:
                QD_file = self.QD_path
            else:
                QD_file = new_QD_path

            if new_file_path is None:
                file_path = self.__raw_data_location
                fig_path = self.save_dir
            else:
                file_path = new_file_path
                fig_path = os.path.split(new_file_path)[0]
            
            if new_QDagent is None:
                QD_savior = QDmanager(QD_file)
                QD_savior.QD_loader()
            else:
                QD_savior = new_QDagent
            
            if new_pic_save_place is not None:
                fig_path = new_pic_save_place

            ds = open_dataset(file_path)
            md = None
            
            for var in ds.data_vars:
                if var.split("_")[-1] != 'x':
                    self.ANA = Multiplex_analyzer("m12")
                    if ds.attrs['method'].lower() == "shot":
                        md = QD_savior.StateDiscriminator.summon_discriminator(var)
                    if QD_savior.rotate_angle[var][0] != 0:
                        ref = QD_savior.rotate_angle[var]
                    else:
                        eyeson_print(f"{var} rotation angle is 0, use contrast to analyze.")
                        ref = QD_savior.refIQ[var]
                    self.ANA._import_data(ds,var_dimension=2,refIQ=ref)
                    self.ANA._start_analysis(var_name=var, OSmodel=md)
                    if self.save_pics:
                        self.ANA._export_result(fig_path)
                    self.ANA.fit_packs.update({"plot_item":self.ANA.plot_item})
                    self.sum_dict[var] = self.ANA.fit_packs
                    """ Storing """
                    if self.histos >= 50:
                        QD_savior.Notewriter.save_echoT2_for(self.ANA.fit_packs["median_T2"],var)
                   
            ds.close()
            if self.keep_QD:
                QD_savior.QD_keeper()
            

    def WorkFlow(self):
        while True:
            self.PrepareHardware()

            self.RunMeasurement()

            self.CloseMeasurement()   
            if not self.want_while:
                break

class CPMG(ExpGovernment):
    def __init__(self,QD_path:str,data_folder:str=None,JOBID:str=None):
        super().__init__()
        self.QD_path = QD_path
        self.save_dir = data_folder
        self.__raw_data_location:str = ""
        self.JOBID = JOBID

    @property
    def RawDataPath(self):
        return self.__raw_data_location

    def SetParameters(self, max_evo_time:float, target_qs:list, pi_num:int, time_sampling_func:str, time_pts_or_step:int|float=100,histo_counts:int=1, avg_n:int=100, execution:bool=True, OSmode:bool=False)->None:
        """ ### Args:
            * max_evo_time = 100e-6\n
            * target_qs = ["q0", "q1", ...]
            * pi_num: 2
            * histo_counts: int, larger than 100 use while loop.\n
            * time_sampling_func (str): 'linspace', 'arange', 'logspace'\n
            * time_pts_or_step: Depends on what sampling func you use, `linspace` or `logspace` set pts, `arange` set step. 
        """
        from qblox_drive_AS.SOP.RabiOsci import sort_elements_2_multiples_of
        if time_sampling_func in ['linspace','logspace','arange']:
            sampling_func:callable = eval(time_sampling_func)
        else:
            raise ValueError(f"Can't recognize the given sampling function name = {time_sampling_func}")
        
        self.time_samples = {}
        self.spin_num = {}
        if sampling_func in [linspace, logspace]:
            for q in sort_dict_with_qidx(target_qs):
                self.spin_num[q] = pi_num
                self.time_samples[q] = sort_elements_2_multiples_of(sampling_func(0, max_evo_time, time_pts_or_step)*1e9,(2*int(pi_num)))*1e-9
        else:
            for q in sort_dict_with_qidx(target_qs):
                self.spin_num[q] = pi_num
                self.time_samples[q] = sampling_func(0, max_evo_time, time_pts_or_step)
        
        self.avg_n = avg_n

        if histo_counts <= 100:
            self.want_while = False
            self.histos = histo_counts
        else:
            self.want_while = True
            self.histos = 1
        
        self.execution = execution
        self.OSmode = OSmode
        
        self.target_qs = sort_dict_with_qidx(target_qs)

        # FPGA memory limit guard
        if self.OSmode:
            for q in self.time_samples:
                if self.avg_n * self.time_samples[q].shape[0] > 131000:
                    raise MemoryError(f"Due to Qblox FPGA memory limit, time_pts * shots must be less than 131000. And you are trying to set {self.avg_n * self.time_samples[q].shape[0]} for {q}")
        
        

    def PrepareHardware(self):
        self.QD_agent, self.cluster, self.meas_ctrl, self.ic, self.Fctrl = init_meas(QuantumDevice_path=self.QD_path)
        if self.OSmode:
            check_OS_model_ready(self.QD_agent, self.target_qs)
        # bias coupler
        self.Fctrl = coupler_zctrl(self.Fctrl,self.QD_agent.Fluxmanager.build_Cctrl_instructions([cp for cp in self.Fctrl if cp[0]=='c' or cp[:2]=='qc'],'i'))
        # offset bias, LO and atte
        for q in self.target_qs:
            self.Fctrl[q](self.QD_agent.Fluxmanager.get_proper_zbiasFor(target_q=q))
            IF_minus = self.QD_agent.Notewriter.get_xyIFFor(q)
            xyf = self.QD_agent.quantum_device.get_element(q).clock_freqs.f01()
            set_LO_frequency(self.QD_agent.quantum_device,q=q,module_type='drive',LO_frequency=xyf-IF_minus)
            init_system_atte(self.QD_agent.quantum_device,[q],ro_out_att=self.QD_agent.Notewriter.get_DigiAtteFor(q, 'ro'), xy_out_att=self.QD_agent.Notewriter.get_DigiAtteFor(q,'xy'))
        
    def RunMeasurement(self):
        from qblox_drive_AS.SOP.T2 import RamseyT2PS
        meas = RamseyT2PS()
        meas.set_time_samples = self.time_samples
        meas._execution
        meas.set_os_mode = self.OSmode
        meas.n_avg = self.avg_n
        meas.set_repeat = self.histos
        meas.set_spin_num = self.spin_num
        meas.set_second_phase = 'x'
        meas.meas_ctrl = self.meas_ctrl
        meas.QD_agent = self.QD_agent
        meas.execution = self.execution
        
        meas.run()
        dataset = meas.dataset
        # dataset = Ramsey(self.QD_agent,self.meas_ctrl,self.time_samples,self.spin_num,self.histos,self.avg_n,self.execution)
        if self.execution:
            if self.save_dir is not None:
                self.save_path = os.path.join(self.save_dir,f"CPMG_{datetime.now().strftime('%Y%m%d%H%M%S') if self.JOBID is None else self.JOBID}")
                self.__raw_data_location = self.save_path + ".nc"
                dataset.to_netcdf(self.__raw_data_location)
                
            else:
                self.save_fig_path = None
        
    def CloseMeasurement(self):
        shut_down(self.cluster,self.Fctrl)


    def RunAnalysis(self,new_QD_path:str=None,new_file_path:str=None,new_QDagent:QDmanager=None,new_pic_save_place:str=None):
        """ User callable analysis function pack """
        
        if self.execution:
            if new_QD_path is None:
                QD_file = self.QD_path
            else:
                QD_file = new_QD_path

            if new_file_path is None:
                file_path = self.__raw_data_location
                fig_path = self.save_dir
            else:
                file_path = new_file_path
                fig_path = os.path.split(new_file_path)[0]

            if new_QDagent is None:
                QD_savior = QDmanager(QD_file)
                QD_savior.QD_loader()
            else:
                QD_savior = new_QDagent 

            if new_pic_save_place is not None:
                fig_path = new_pic_save_place

            ds = open_dataset(file_path)
            md = None

            for var in ds.data_vars:
                if var.split("_")[-1] != 'x':
                    self.ANA = Multiplex_analyzer("m12")
                    if ds.attrs['method'].lower() == "shot":
                        md = QD_savior.StateDiscriminator.summon_discriminator(var)
                    if QD_savior.rotate_angle[var][0] != 0:
                        ref = QD_savior.rotate_angle[var]
                    else:
                        eyeson_print(f"{var} rotation angle is 0, use contrast to analyze.")
                        ref = QD_savior.refIQ[var]
                    self.ANA._import_data(ds,var_dimension=2,refIQ=ref)
                    self.ANA._start_analysis(var_name=var, OSmodel=md)
                    if self.save_pics:
                        self.ANA._export_result(fig_path)
                    self.ANA.fit_packs.update({"plot_item":self.ANA.plot_item})
                    self.sum_dict[var] = self.ANA.fit_packs

                    """ Storing """
                    if self.histos >= 50:
                        QD_savior.Notewriter.save_echoT2_for(self.ANA.fit_packs["median_T2"],var)
                   
            ds.close()
            if self.keep_QD:
                QD_savior.QD_keeper()
            

    def WorkFlow(self, freq_detune_Hz:float=None):
        while True:
            self.PrepareHardware()
            
            if freq_detune_Hz is not None:
                for q in self.target_qs:
                    self.QD_agent.quantum_device.get_element(q).clock_freqs.f01(self.QD_agent.quantum_device.get_element(q).clock_freqs.f01()+freq_detune_Hz)

            self.RunMeasurement()

            self.CloseMeasurement()   
            if not self.want_while:
                break

class EnergyRelaxation(ExpGovernment):
    def __init__(self,QD_path:str,data_folder:str=None,JOBID:str=None):
        super().__init__()
        self.QD_path = QD_path
        self.save_dir = data_folder
        self.__raw_data_location:str = ""
        self.JOBID = JOBID

    @property
    def RawDataPath(self):
        return self.__raw_data_location

    def SetParameters(self, max_evo_time:float, target_qs:list, time_sampling_func:str, time_pts_or_step:int|float=100,histo_counts:int=1, avg_n:int=100, execution:bool=True, OSmode:bool=False)->None:
        """ ### Args:
            * max_evo_time: 200e-6\n
            * target_qs: ["q0", "q1", ..]
            * histo_counts: int, larger than 100 use while loop.\n
            * time_sampling_func (str): 'linspace', 'arange', 'logspace'\n
            * time_pts_or_step: Depends on what sampling func you use, `linspace` or `logspace` set pts, `arange` set step. 
        """
        from qblox_drive_AS.SOP.RabiOsci import sort_elements_2_multiples_of
        if time_sampling_func in ['linspace','logspace','arange']:
            sampling_func:callable = eval(time_sampling_func)
        else:
            raise ValueError(f"Can't recognize the given sampling function name = {time_sampling_func}")
        
        self.time_samples = {}
        if sampling_func in [linspace, logspace]:
            for q in sort_dict_with_qidx(target_qs):
                self.time_samples[q] = sort_elements_2_multiples_of(sampling_func(4e-9,max_evo_time,time_pts_or_step)*1e9,1)*1e-9
        else:
            for q in sort_dict_with_qidx(target_qs):
                self.time_samples[q] = sampling_func(4e-9,max_evo_time,time_pts_or_step)

        self.avg_n = avg_n

        if histo_counts <= 100:
            self.want_while = False
            self.histos = histo_counts
        else:
            self.want_while = True
            self.histos = 1
        
        self.execution = execution
        self.OSmode = OSmode
        self.target_qs = sort_dict_with_qidx(target_qs)

        # FPGA memory limit guard
        if self.OSmode:
            for q in self.time_samples:
                if self.avg_n * self.time_samples[q].shape[0] > 131000:
                    raise MemoryError(f"Due to Qblox FPGA memory limit, time_pts * shots must be less than 131000. And you are trying to set {self.avg_n * self.time_samples[q].shape[0]} for {q}")
        

    def PrepareHardware(self):
        self.QD_agent, self.cluster, self.meas_ctrl, self.ic, self.Fctrl = init_meas(QuantumDevice_path=self.QD_path)
        if self.OSmode:
            check_OS_model_ready(self.QD_agent, self.target_qs)
        # bias coupler
        self.Fctrl = coupler_zctrl(self.Fctrl,self.QD_agent.Fluxmanager.build_Cctrl_instructions([cp for cp in self.Fctrl if cp[0]=='c' or cp[:2]=='qc'],'i'))
        # offset bias, LO and atte
        for q in self.target_qs:
            self.Fctrl[q](self.QD_agent.Fluxmanager.get_proper_zbiasFor(target_q=q))
            IF_minus = self.QD_agent.Notewriter.get_xyIFFor(q)
            xyf = self.QD_agent.quantum_device.get_element(q).clock_freqs.f01()
            set_LO_frequency(self.QD_agent.quantum_device,q=q,module_type='drive',LO_frequency=xyf-IF_minus)
            init_system_atte(self.QD_agent.quantum_device,[q],ro_out_att=self.QD_agent.Notewriter.get_DigiAtteFor(q, 'ro'), xy_out_att=self.QD_agent.Notewriter.get_DigiAtteFor(q,'xy'))
        
    def RunMeasurement(self):
        from qblox_drive_AS.SOP.T1 import EnergyRelaxPS
        meas = EnergyRelaxPS()
        meas.set_time_samples = self.time_samples
        meas.set_os_mode = self.OSmode
        meas.n_avg = self.avg_n
        meas.set_repeat = self.histos
        meas.meas_ctrl = self.meas_ctrl
        meas.QD_agent = self.QD_agent
        meas.execution = self.execution
        
        meas.run()
        dataset = meas.dataset
        if self.execution:
            if self.save_dir is not None:
                self.save_path = os.path.join(self.save_dir,f"T1_{datetime.now().strftime('%Y%m%d%H%M%S') if self.JOBID is None else self.JOBID}")
                self.__raw_data_location = self.save_path + ".nc"
                dataset.to_netcdf(self.__raw_data_location)
                
            else:
                self.save_fig_path = None
        
    def CloseMeasurement(self):
        shut_down(self.cluster,self.Fctrl)


    def RunAnalysis(self,new_QD_path:str=None,new_file_path:str=None,new_QDagent:QDmanager=None,new_pic_save_place:str=None):
        """ User callable analysis function pack """
        
        if self.execution:
            if new_QD_path is None:
                QD_file = self.QD_path
            else:
                QD_file = new_QD_path

            if new_file_path is None:
                file_path = self.__raw_data_location
                fig_path = self.save_dir
            else:
                file_path = new_file_path
                fig_path = os.path.split(new_file_path)[0]

            if new_QDagent is None:
                QD_savior = QDmanager(QD_file)
                QD_savior.QD_loader()
            else:
                QD_savior = new_QDagent

            if new_pic_save_place is not None:
                fig_path = new_pic_save_place

            ds = open_dataset(file_path)
            md = None  # model for one shot analysis
            
            for var in ds.data_vars:
                if var.split("_")[-1] != 'x':
                    if ds.attrs['method'].lower() == "shot":
                        md = QD_savior.StateDiscriminator.summon_discriminator(var)
                        
                    self.ANA = Multiplex_analyzer("m13")
                    if QD_savior.rotate_angle[var][0] != 0:
                        ref = QD_savior.rotate_angle[var]
                    else:
                        eyeson_print(f"{var} rotation angle is 0, use contrast to analyze.")
                        ref = QD_savior.refIQ[var]
                    self.ANA._import_data(ds,var_dimension=2,refIQ=ref)
                    self.ANA._start_analysis(var_name=var, OSmodel=md)
                    if self.save_pics:
                        self.ANA._export_result(fig_path)


                    self.ANA.fit_packs.update({"plot_item":self.ANA.plot_item})
                    self.sum_dict[var] = self.ANA.fit_packs
                    

                    """ Storing """
                    if self.histos >= 50:
                        QD_savior.Notewriter.save_T1_for(self.ANA.fit_packs["median_T1"],var)

            ds.close()
            if self.keep_QD:
                QD_savior.QD_keeper()
            

    def WorkFlow(self):
        while True:
            self.PrepareHardware()

            self.RunMeasurement()

            self.CloseMeasurement()   
            if not self.want_while:
                break

class XYFcali(ExpGovernment):
    def __init__(self,QD_path:str,data_folder:str=None,JOBID:str=None):
        super().__init__()
        self.QD_path = QD_path
        self.save_dir = data_folder
        self.__raw_data_location:str = ""
        self.JOBID = JOBID

    @property
    def RawDataPath(self):
        return self.__raw_data_location

    def SetParameters(self, target_qs:list, evo_time:float=0.5e-6, detu:float=0, avg_n:int=100, execution:bool=True, OSmode:bool=False)->None:
        """ ### Args:
            * target_qs: ["q0", "q1", ...]\n
        """
        from qblox_drive_AS.SOP.RabiOsci import sort_elements_2_multiples_of
    
        self.time_samples = {}
        for q in sort_dict_with_qidx(target_qs):
            self.time_samples[q] = sort_elements_2_multiples_of(linspace(40e-9,evo_time,100)*1e9,4)*1e-9
        self.detu = detu
        self.avg_n = avg_n
        self.execution = execution
        self.OSmode = OSmode
        self.spin_num = {}
        self.target_qs = sort_dict_with_qidx(target_qs)
        

    def PrepareHardware(self):
        self.QD_agent, self.cluster, self.meas_ctrl, self.ic, self.Fctrl = init_meas(QuantumDevice_path=self.QD_path)
        # bias coupler
        self.Fctrl = coupler_zctrl(self.Fctrl,self.QD_agent.Fluxmanager.build_Cctrl_instructions([cp for cp in self.Fctrl if cp[0]=='c' or cp[:2]=='qc'],'i'))
        # offset bias, LO and atte
        for q in self.target_qs:
            self.Fctrl[q](self.QD_agent.Fluxmanager.get_proper_zbiasFor(target_q=q))
            IF_minus = self.QD_agent.Notewriter.get_xyIFFor(q)
            xyf = self.QD_agent.quantum_device.get_element(q).clock_freqs.f01()+self.detu
            self.QD_agent.quantum_device.get_element(q).clock_freqs.f01(xyf)
            set_LO_frequency(self.QD_agent.quantum_device,q=q,module_type='drive',LO_frequency=xyf-IF_minus)
            init_system_atte(self.QD_agent.quantum_device,[q],ro_out_att=self.QD_agent.Notewriter.get_DigiAtteFor(q, 'ro'), xy_out_att=self.QD_agent.Notewriter.get_DigiAtteFor(q,'xy'))
        
    def RunMeasurement(self):
        from qblox_drive_AS.SOP.T2 import RamseyT2PS
        meas = RamseyT2PS()
        meas.set_time_samples = self.time_samples
        meas.set_os_mode = self.OSmode
        meas.n_avg = self.avg_n
        meas.set_repeat = 1
        meas.set_spin_num = self.spin_num
        meas.set_second_phase = 'y'
        meas.meas_ctrl = self.meas_ctrl
        meas.QD_agent = self.QD_agent
        meas.execution = self.execution
        
        meas.run()
        dataset = meas.dataset
        # dataset = Ramsey(self.QD_agent,self.meas_ctrl,self.time_samples,self.spin_num,1,self.avg_n,self.execution,second_phase='y')
        if self.execution:
            if self.save_dir is not None:
                self.save_path = os.path.join(self.save_dir,f"XYFcali_{datetime.now().strftime('%Y%m%d%H%M%S') if self.JOBID is None else self.JOBID}")
                self.__raw_data_location = self.save_path + ".nc"
                dataset.to_netcdf(self.__raw_data_location)
                
            else:
                self.save_fig_path = None
        
    def CloseMeasurement(self):
        shut_down(self.cluster,self.Fctrl)


    def RunAnalysis(self,new_QD_path:str=None,new_file_path:str=None):
        """ User callable analysis function pack """
        
        if self.execution:
            if new_QD_path is None:
                QD_file = self.QD_path
            else:
                QD_file = new_QD_path

            if new_file_path is None:
                file_path = self.__raw_data_location
                fig_path = self.save_dir
            else:
                file_path = new_file_path
                fig_path = os.path.split(new_file_path)[0]

            QD_savior = QDmanager(QD_file)
            QD_savior.QD_loader()

            ds = open_dataset(file_path)
            answer = {}
            for var in ds.data_vars:
                if var.split("_")[-1] != 'x':
                    ANA = Multiplex_analyzer("c2")
                    if QD_savior.rotate_angle[var][0] != 0:
                        ref = QD_savior.rotate_angle[var]
                    else:
                        eyeson_print(f"{var} rotation angle is 0, use contrast to analyze.")
                        ref = QD_savior.refIQ[var]
                    
                    ANA._import_data(ds,var_dimension=2,refIQ=ref)
                    ANA._start_analysis(var_name=var)
                    ANA._export_result(fig_path)

                    if (ANA.fit_packs['phase'] % 360 + 360) % 360 > 180:
                        sign = -1
                    else:
                        sign = 1
                    
                    answer[var] = sign*ANA.fit_packs['freq']
                    highlight_print(f"{var}: actual detune = {round(answer[var]*1e-6,4)} MHz")
            ds.close()

            permi = mark_input(f"What qubit can be updated ? {list(answer.keys())}/ all/ no ").lower()
            if permi in list(answer.keys()):
                QD_savior.quantum_device.get_element(permi).clock_freqs.f01(QD_savior.quantum_device.get_element(permi).clock_freqs.f01()-answer[permi])
                QD_savior.QD_keeper()
            elif permi in ["all",'y','yes']:
                for q in answer:
                    QD_savior.quantum_device.get_element(q).clock_freqs.f01(QD_savior.quantum_device.get_element(q).clock_freqs.f01()-answer[q])
                QD_savior.QD_keeper()
            else:
                print("Updating got denied ~")

    def WorkFlow(self):
        
        self.PrepareHardware()

        self.RunMeasurement()

        self.CloseMeasurement()   

class ROFcali(ExpGovernment):
    def __init__(self,QD_path:str,data_folder:str=None,JOBID:str=None):
        super().__init__()
        self.QD_path = QD_path
        self.save_dir = data_folder
        self.__raw_data_location:str = ""
        self.JOBID = JOBID

    @property
    def RawDataPath(self):
        return self.__raw_data_location

    def SetParameters(self, freq_span_range:dict, freq_pts:int=100, avg_n:int=100, execution:bool=True, OSmode:bool=False)->None:
        """ ### Args:
            * freq_span_range: {"q0":[freq_span_start, freq_span_end], ....}\n
        """
        self.freq_samples = {}
        self.tempor_freq = [freq_span_range, freq_pts]

        self.avg_n = avg_n
        self.execution = execution
        self.OSmode = OSmode
        self.target_qs = sort_dict_with_qidx(list(freq_span_range.keys()))
        

    def PrepareHardware(self):
        self.QD_agent, self.cluster, self.meas_ctrl, self.ic, self.Fctrl = init_meas(QuantumDevice_path=self.QD_path)
        # bias coupler
        self.Fctrl = coupler_zctrl(self.Fctrl,self.QD_agent.Fluxmanager.build_Cctrl_instructions([cp for cp in self.Fctrl if cp[0]=='c' or cp[:2]=='qc'],'i'))
        # offset bias, LO and atte
        for q in self.target_qs:
            self.Fctrl[q](self.QD_agent.Fluxmanager.get_proper_zbiasFor(target_q=q))
            IF_minus = self.QD_agent.Notewriter.get_xyIFFor(q)
            xyf = self.QD_agent.quantum_device.get_element(q).clock_freqs.f01()
            set_LO_frequency(self.QD_agent.quantum_device,q=q,module_type='drive',LO_frequency=xyf-IF_minus)
            init_system_atte(self.QD_agent.quantum_device,[q],ro_out_att=self.QD_agent.Notewriter.get_DigiAtteFor(q, 'ro'), xy_out_att=self.QD_agent.Notewriter.get_DigiAtteFor(q,'xy'))
        
            rof = self.QD_agent.quantum_device.get_element(q).clock_freqs.readout()
            self.freq_samples[q] = linspace(rof+self.tempor_freq[0][q][0],rof+self.tempor_freq[0][q][1],self.tempor_freq[1])
        
    def RunMeasurement(self):
        from qblox_drive_AS.Calibration_exp.RofCali import ROFcalibrationPS
        meas = ROFcalibrationPS()
        meas.ro_elements = self.freq_samples
        meas.execution = self.execution
        meas.n_avg = self.avg_n
        meas.meas_ctrl = self.meas_ctrl
        meas.QD_agent = self.QD_agent
        meas.run()
        dataset = meas.dataset
        
        if self.execution:
            if self.save_dir is not None:
                self.save_path = os.path.join(self.save_dir,f"ROFcali_{datetime.now().strftime('%Y%m%d%H%M%S') if self.JOBID is None else self.JOBID}")
                self.__raw_data_location = self.save_path + ".nc"
                dataset.to_netcdf(self.__raw_data_location)
                
            else:
                self.save_fig_path = None
        
    def CloseMeasurement(self):
        shut_down(self.cluster,self.Fctrl)


    def RunAnalysis(self,new_QD_path:str=None,new_file_path:str=None):
        """ User callable analysis function pack """
        
        if self.execution:
            if new_QD_path is None:
                QD_file = self.QD_path
            else:
                QD_file = new_QD_path

            if new_file_path is None:
                file_path = self.__raw_data_location
                fig_path = self.save_dir
            else:
                file_path = new_file_path
                fig_path = os.path.split(new_file_path)[0]

            QD_savior = QDmanager(QD_file)
            QD_savior.QD_loader()

            ds = open_dataset(file_path)
            answer = {}
            for var in ds.data_vars:
                if var.split("_")[-1] != 'rof':
                    ANA = Multiplex_analyzer("c1")
                    ANA._import_data(ds,var_dimension=1)
                    ANA._start_analysis(var_name = var)
                    ANA._export_result(fig_path)
                    answer[var] = ANA.fit_packs[var]["optimal_rof"]
            ds.close()

            permi = mark_input(f"What qubit can be updated ? {list(answer.keys())}/ all/ no ").lower()
            if permi in list(answer.keys()):
                QD_savior.quantum_device.get_element(permi).clock_freqs.readout(answer[permi])
                QD_savior.QD_keeper()
            elif permi in ["all",'y','yes']:
                for q in answer:
                    QD_savior.quantum_device.get_element(q).clock_freqs.readout(answer[q])
                QD_savior.QD_keeper()
            else:
                print("Updating got denied ~")


    def WorkFlow(self):
        
        self.PrepareHardware()

        self.RunMeasurement()

        self.CloseMeasurement() 

class PiAcali(ExpGovernment):
    def __init__(self,QD_path:str,data_folder:str=None,JOBID:str=None):
        super().__init__()
        self.QD_path = QD_path
        self.save_dir = data_folder
        self.__raw_data_location:str = ""
        self.JOBID = JOBID

    @property
    def RawDataPath(self):
        return self.__raw_data_location

    def SetParameters(self, piamp_coef_range:dict, amp_sampling_funct:str, coef_ptsORstep:int=100, pi_pair_num:list=[2,3], avg_n:int=100, execution:bool=True, OSmode:bool=False)->None:
        """ ### Args:
            * piamp_coef_range: {"q0":[0.9, 1.1], "q1":[0.95, 1.15], ...]\n
            * amp_sampling_funct: str, `linspace` or `arange`.\n
            * pi_pair_num: list, like [2, 3] will try 2 exp, the first uses 2\*2 pi-pulse, and the second exp uses 3*2 pi-pulse
        """
        if amp_sampling_funct in ['linspace','logspace','arange']:
            sampling_func:callable = eval(amp_sampling_funct)
        else:
            raise ValueError(f"Can't recognize the given sampling function name = {amp_sampling_funct}")
        
        self.amp_coef_samples = {}
        for q in sort_dict_with_qidx(piamp_coef_range):
           self.amp_coef_samples[q] = sampling_func(*piamp_coef_range[q],coef_ptsORstep)
        
        self.pi_pair_num = pi_pair_num
        self.avg_n = avg_n
        self.execution = execution
        self.OSmode = OSmode
        self.target_qs = sort_dict_with_qidx(list(piamp_coef_range.keys()))
        

    def PrepareHardware(self):
        self.QD_agent, self.cluster, self.meas_ctrl, self.ic, self.Fctrl = init_meas(QuantumDevice_path=self.QD_path)
        # bias coupler
        self.Fctrl = coupler_zctrl(self.Fctrl,self.QD_agent.Fluxmanager.build_Cctrl_instructions([cp for cp in self.Fctrl if cp[0]=='c' or cp[:2]=='qc'],'i'))
        # offset bias, LO and atte
        for q in self.target_qs:
            self.Fctrl[q](self.QD_agent.Fluxmanager.get_proper_zbiasFor(target_q=q))
            IF_minus = self.QD_agent.Notewriter.get_xyIFFor(q)
            xyf = self.QD_agent.quantum_device.get_element(q).clock_freqs.f01()
            set_LO_frequency(self.QD_agent.quantum_device,q=q,module_type='drive',LO_frequency=xyf-IF_minus)
            init_system_atte(self.QD_agent.quantum_device,[q],ro_out_att=self.QD_agent.Notewriter.get_DigiAtteFor(q, 'ro'), xy_out_att=self.QD_agent.Notewriter.get_DigiAtteFor(q,'xy'))

        
    def RunMeasurement(self):
        from qblox_drive_AS.Calibration_exp.PI_ampCali import PiAcalibrationPS
        meas = PiAcalibrationPS()
        meas.ro_elements = self.amp_coef_samples
        meas.pi_pairs = self.pi_pair_num
        meas.execution = self.execution
        meas.n_avg = self.avg_n
        meas.meas_ctrl = self.meas_ctrl
        meas.QD_agent = self.QD_agent
        meas.run()
        dataset = meas.dataset
    
        
        if self.execution:
            if self.save_dir is not None:
                self.save_path = os.path.join(self.save_dir,f"PIampcali_{datetime.now().strftime('%Y%m%d%H%M%S') if self.JOBID is None else self.JOBID}")
                self.__raw_data_location = self.save_path + ".nc"
                dataset.to_netcdf(self.__raw_data_location)
                
            else:
                self.save_fig_path = None
        
    def CloseMeasurement(self):
        shut_down(self.cluster,self.Fctrl)


    def RunAnalysis(self,new_QD_path:str=None,new_file_path:str=None):
        """ User callable analysis function pack """
        
        if self.execution:
            if new_QD_path is None:
                QD_file = self.QD_path
            else:
                QD_file = new_QD_path

            if new_file_path is None:
                file_path = self.__raw_data_location
                fig_path = self.save_dir
            else:
                file_path = new_file_path
                fig_path = os.path.split(new_file_path)[0]

            QD_savior = QDmanager(QD_file)
            QD_savior.QD_loader()

            ds = open_dataset(file_path)
            answer = {}
            for var in ds.data_vars:
                if var.split("_")[-1] != 'PIcoef':
                    if QD_savior.rotate_angle[var][0] != 0:
                        ref = QD_savior.rotate_angle[var]
                    else:
                        eyeson_print(f"{var} rotation angle is 0, use contrast to analyze.")
                        ref = QD_savior.refIQ[var]
                    ANA = Multiplex_analyzer("c3")
                    ANA._import_data(ds,var_dimension=1,refIQ=ref)
                    ANA._start_analysis(var_name = var)
                    ANA._export_result(fig_path)
                    answer[var] = ANA.fit_packs["ans"]
            ds.close()

            permi = mark_input(f"What qubit can be updated ? {list(answer.keys())}/ all/ no ").lower()
            if permi in list(answer.keys()):
                QD_savior.quantum_device.get_element(permi).rxy.amp180(QD_savior.quantum_device.get_element(permi).rxy.amp180()*answer[permi])
                QD_savior.QD_keeper()
            elif permi in ["all",'y','yes']:
                for q in answer:
                    QD_savior.quantum_device.get_element(q).rxy.amp180(QD_savior.quantum_device.get_element(q).rxy.amp180()*answer[q])
                QD_savior.QD_keeper()
            else:
                print("Updating got denied ~")

    def WorkFlow(self):
        
        self.PrepareHardware()

        self.RunMeasurement()

        self.CloseMeasurement() 

class hPiAcali(ExpGovernment):
    def __init__(self,QD_path:str,data_folder:str=None,JOBID:str=None):
        super().__init__()
        self.QD_path = QD_path
        self.save_dir = data_folder
        self.__raw_data_location:str = ""
        self.JOBID = JOBID

    @property
    def RawDataPath(self):
        return self.__raw_data_location

    def SetParameters(self, half_piamp_coef_range:list, target_qs:list, amp_sampling_funct:str, coef_ptsORstep:int=100, halfPi_pair_num:list=[3,5], avg_n:int=100, execution:bool=True, OSmode:bool=False)->None:
        """ ### Args:
            * piamp_coef_range: [0.9, 1.1].\n
            *target_qs: ["q0", "q1", ...]
            * amp_sampling_funct: str, `linspace` or `arange`.\n
            * pi_pair_num: list, like [3, 5] will try 2 exp, the first uses 3\*4 half pi-pulse, and the second exp uses 5*4 half pi-pulse
        """
        if amp_sampling_funct in ['linspace','logspace','arange']:
            sampling_func:callable = eval(amp_sampling_funct)
        else:
            raise ValueError(f"Can't recognize the given sampling function name = {amp_sampling_funct}")
        
        self.amp_coef_samples = {}
        for q in sort_dict_with_qidx(target_qs):
           self.amp_coef_samples[q] = sampling_func(*half_piamp_coef_range,coef_ptsORstep)
        self.halfPi_pair_num = halfPi_pair_num
        self.avg_n = avg_n
        self.execution = execution
        self.OSmode = OSmode
        self.target_qs = sort_dict_with_qidx(target_qs)
        

    def PrepareHardware(self):
        self.QD_agent, self.cluster, self.meas_ctrl, self.ic, self.Fctrl = init_meas(QuantumDevice_path=self.QD_path)
        # bias coupler
        self.Fctrl = coupler_zctrl(self.Fctrl,self.QD_agent.Fluxmanager.build_Cctrl_instructions([cp for cp in self.Fctrl if cp[0]=='c' or cp[:2]=='qc'],'i'))
        # offset bias, LO and atte
        for q in self.target_qs:
            self.Fctrl[q](self.QD_agent.Fluxmanager.get_proper_zbiasFor(target_q=q))
            IF_minus = self.QD_agent.Notewriter.get_xyIFFor(q)
            xyf = self.QD_agent.quantum_device.get_element(q).clock_freqs.f01()
            set_LO_frequency(self.QD_agent.quantum_device,q=q,module_type='drive',LO_frequency=xyf-IF_minus)
            init_system_atte(self.QD_agent.quantum_device,[q],ro_out_att=self.QD_agent.Notewriter.get_DigiAtteFor(q, 'ro'), xy_out_att=self.QD_agent.Notewriter.get_DigiAtteFor(q,'xy'))

        
    def RunMeasurement(self):
        from qblox_drive_AS.Calibration_exp.halfPI_ampCali import hPiAcalibrationPS
        meas = hPiAcalibrationPS()
        meas.ro_elements = self.amp_coef_samples
        meas.hpi_quads = self.halfPi_pair_num
        meas.execution = self.execution
        meas.n_avg = self.avg_n
        meas.meas_ctrl = self.meas_ctrl
        meas.QD_agent = self.QD_agent
        meas.run()
        dataset = meas.dataset
        
        if self.execution:
            if self.save_dir is not None:
                self.save_path = os.path.join(self.save_dir,f"halfPIampcali_{datetime.now().strftime('%Y%m%d%H%M%S') if self.JOBID is None else self.JOBID}")
                self.__raw_data_location = self.save_path + ".nc"
                dataset.to_netcdf(self.__raw_data_location)
                
            else:
                self.save_fig_path = None
        
    def CloseMeasurement(self):
        shut_down(self.cluster,self.Fctrl)


    def RunAnalysis(self,new_QD_path:str=None,new_file_path:str=None):
        """ User callable analysis function pack """
        
        if self.execution:
            if new_QD_path is None:
                QD_file = self.QD_path
            else:
                QD_file = new_QD_path

            if new_file_path is None:
                file_path = self.__raw_data_location
                fig_path = self.save_dir
            else:
                file_path = new_file_path
                fig_path = os.path.split(new_file_path)[0]

            QD_savior = QDmanager(QD_file)
            QD_savior.QD_loader()

            ds = open_dataset(file_path)
            answer = {}
            for var in ds.data_vars:
                if var.split("_")[-1] != 'HalfPIcoef':
                    if QD_savior.rotate_angle[var][0] != 0:
                        ref = QD_savior.rotate_angle[var]
                    else:
                        eyeson_print(f"{var} rotation angle is 0, use contrast to analyze.")
                        ref = QD_savior.refIQ[var]
                    ANA = Multiplex_analyzer("c4")
                    ANA._import_data(ds,var_dimension=1,refIQ=ref)
                    ANA._start_analysis(var_name = var) 
                    ANA._export_result(fig_path)
                    answer[var] = ANA.fit_packs["ans"]

            ds.close()
            permi = mark_input(f"What qubit can be updated ? {list(answer.keys())}/ all/ no ").lower()
            if permi in list(answer.keys()):
                QD_savior.Waveformer.set_halfPIratio_for(permi, QD_savior.Waveformer.get_halfPIratio_for(permi)*answer[permi])
                QD_savior.QD_keeper()
            elif permi in ["all",'y','yes']:
                for q in answer:
                    QD_savior.Waveformer.set_halfPIratio_for(q, QD_savior.Waveformer.get_halfPIratio_for(q)*answer[q])
                QD_savior.QD_keeper()
            else:
                print("Updating got denied ~")
    def WorkFlow(self):
        
        self.PrepareHardware()

        self.RunMeasurement()

        self.CloseMeasurement() 

class ROLcali(ExpGovernment):
    def __init__(self,QD_path:str,data_folder:str=None,JOBID:str=None):
        super().__init__()
        self.QD_path = QD_path
        self.save_dir = data_folder
        self.__raw_data_location:str = ""
        self.JOBID = JOBID

    @property
    def RawDataPath(self):
        return self.__raw_data_location

    def SetParameters(self, roamp_coef_range:dict, coef_sampling_func:str, ro_coef_ptsORstep:int=100, avg_n:int=100, execution:bool=True, OSmode:bool=False)->None:
        """ ### Args:
            * roamp_coef_range: {"q0":[0.85, 1.3], ... }, rule:  q_name:[roamp_coef_start, roamp_coef_end]. exp with ro-amp *=  roamp_coef\n
            * coef_sampling_func: str, `'linspace'` or `'arange'`.
        """
        if coef_sampling_func in ['linspace','logspace','arange']:
            sampling_func:callable = eval(coef_sampling_func)
        else:
            raise ValueError(f"Can't recognize the given sampling function name = {coef_sampling_func}")
        
        self.amp_coef_samples = {}
        for q in sort_dict_with_qidx(roamp_coef_range):
           self.amp_coef_samples[q] = sampling_func(*roamp_coef_range[q],ro_coef_ptsORstep)

        self.avg_n = avg_n
        self.execution = execution
        self.OSmode = OSmode
        self.target_qs = sort_dict_with_qidx(list(roamp_coef_range.keys()))
        

    def PrepareHardware(self):
        self.QD_agent, self.cluster, self.meas_ctrl, self.ic, self.Fctrl = init_meas(QuantumDevice_path=self.QD_path)
        # bias coupler
        self.Fctrl = coupler_zctrl(self.Fctrl,self.QD_agent.Fluxmanager.build_Cctrl_instructions([cp for cp in self.Fctrl if cp[0]=='c' or cp[:2]=='qc'],'i'))
        # offset bias, LO and atte
        for q in self.target_qs:
            self.Fctrl[q](self.QD_agent.Fluxmanager.get_proper_zbiasFor(target_q=q))
            IF_minus = self.QD_agent.Notewriter.get_xyIFFor(q)
            xyf = self.QD_agent.quantum_device.get_element(q).clock_freqs.f01()
            set_LO_frequency(self.QD_agent.quantum_device,q=q,module_type='drive',LO_frequency=xyf-IF_minus)
            init_system_atte(self.QD_agent.quantum_device,[q],ro_out_att=self.QD_agent.Notewriter.get_DigiAtteFor(q, 'ro'), xy_out_att=self.QD_agent.Notewriter.get_DigiAtteFor(q,'xy'))

        
    def RunMeasurement(self):
        from qblox_drive_AS.Calibration_exp.RO_ampCali import ROLcalibrationPS
        meas = ROLcalibrationPS()
        meas.power_samples = self.amp_coef_samples
        meas.execution = self.execution
        meas.n_avg = self.avg_n
        meas.meas_ctrl = self.meas_ctrl
        meas.QD_agent = self.QD_agent
        meas.run()
        dataset = meas.dataset
        
        if self.execution:
            if self.save_dir is not None:
                self.save_path = os.path.join(self.save_dir,f"ROLcali_{datetime.now().strftime('%Y%m%d%H%M%S') if self.JOBID is None else self.JOBID}")
                self.__raw_data_location = self.save_path + ".nc"
                dataset.to_netcdf(self.__raw_data_location)
                
            else:
                self.save_fig_path = None
        
    def CloseMeasurement(self):
        shut_down(self.cluster,self.Fctrl)


    def RunAnalysis(self,new_QD_path:str=None,new_file_path:str=None):
        """ User callable analysis function pack """
        
        if self.execution:
            if new_QD_path is None:
                QD_file = self.QD_path
            else:
                QD_file = new_QD_path

            if new_file_path is None:
                file_path = self.__raw_data_location
                fig_path = self.save_dir
            else:
                file_path = new_file_path
                fig_path = os.path.split(new_file_path)[0]

            QD_savior = QDmanager(QD_file)
            QD_savior.QD_loader()

            ds = open_dataset(file_path)
            
            for var in ds.data_vars:
                if var.split("_")[-1] != 'rol':
                    ANA = Multiplex_analyzer("c5")
                    ANA._import_data(ds,var_dimension=1)
                    ANA._start_analysis(var_name = var)
                    ANA._export_result(fig_path)
                    
            ds.close()


    def WorkFlow(self):
        
        self.PrepareHardware()

        self.RunMeasurement()

        self.CloseMeasurement() 

class ZgateEnergyRelaxation(ExpGovernment):
    def __init__(self,QD_path:str,data_folder:str=None,JOBID:str=None):
        super().__init__()
        self.QD_path = QD_path
        self.save_dir = data_folder
        self.__raw_data_location:str = ""
        self.JOBID = JOBID

    @property
    def RawDataPath(self):
        return self.__raw_data_location

    def SetParameters(self, max_evo_time:float, target_qs:list, time_sampling_func:str, bias_range:list, prepare_excited:bool=True, bias_sample_func:str='linspace', time_pts_or_step:int|float=100,Whileloop:bool=False, avg_n:int=100, execution:bool=True, OSmode:bool=False)->None:
        """ ### Args:
            * max_evo_time: 100e-6\n
            * target_qs: ["q0", "q1", ...]
            * prepare_excited: True, prepare excited state, False prepare ground state
            * whileloop: bool, use while loop or not.\n
            * time_sampling_func (str): 'linspace', 'arange', 'logspace'\n
            * time_pts_or_step: Depends on what sampling func you use, `linspace` or `logspace` set pts, `arange` set step.\n
            * bias_range:list, [z_amp_start, z_amp_end, pts/step]\n
            * bias_sampling_func:str, `linspace`(default) or `arange`. 
        """
        from qblox_drive_AS.SOP.RabiOsci import sort_elements_2_multiples_of
        if time_sampling_func in ['linspace','logspace','arange']:
            sampling_func:callable = eval(time_sampling_func)
        else:
            raise ValueError(f"Can't recognize the given sampling function name = {time_sampling_func}")
        
        self.time_samples = {}
        if sampling_func in [linspace, logspace]:
            for q in sort_dict_with_qidx(target_qs):
                self.time_samples[q] = sort_elements_2_multiples_of(sampling_func(4e-9, max_evo_time)*1e9,4)*1e-9
        else:
            for q in sort_dict_with_qidx(target_qs):
                self.time_samples[q] = sampling_func(4e-9, max_evo_time,time_pts_or_step)

        self.avg_n = avg_n
        if bias_sample_func in ['linspace', 'arange']:
            self.bias_samples = eval(bias_sample_func)(*bias_range)
        else:
            raise ValueError(f"bias sampling function must be 'linspace' or 'arange' !")
        self.want_while = Whileloop
        self.prepare_1 = int(prepare_excited)
        self.execution = execution
        self.OSmode = OSmode
        self.target_qs = sort_dict_with_qidx(target_qs)
        

    def PrepareHardware(self):
        self.QD_agent, self.cluster, self.meas_ctrl, self.ic, self.Fctrl = init_meas(QuantumDevice_path=self.QD_path)
        # bias coupler
        self.Fctrl = coupler_zctrl(self.Fctrl,self.QD_agent.Fluxmanager.build_Cctrl_instructions([cp for cp in self.Fctrl if cp[0]=='c' or cp[:2]=='qc'],'i'))
        # offset bias, LO and atte
        for q in self.target_qs:
            self.Fctrl[q](self.QD_agent.Fluxmanager.get_proper_zbiasFor(target_q=q))
            IF_minus = self.QD_agent.Notewriter.get_xyIFFor(q)
            xyf = self.QD_agent.quantum_device.get_element(q).clock_freqs.f01()
            set_LO_frequency(self.QD_agent.quantum_device,q=q,module_type='drive',LO_frequency=xyf-IF_minus)
            init_system_atte(self.QD_agent.quantum_device,[q],ro_out_att=self.QD_agent.Notewriter.get_DigiAtteFor(q, 'ro'), xy_out_att=self.QD_agent.Notewriter.get_DigiAtteFor(q,'xy'))
        
    def RunMeasurement(self):
        from qblox_drive_AS.aux_measurement.ZgateT1 import ZEnergyRelaxPS
        meas = ZEnergyRelaxPS()
        meas.set_time_samples = self.time_samples
        meas.z_samples = self.bias_samples
        meas.set_os_mode = self.OSmode
        meas.set_n_avg = self.avg_n
        meas.pre_state = self.prepare_1
        meas.meas_ctrl = self.meas_ctrl
        meas.QD_agent = self.QD_agent
        meas.execution = self.execution
        
        meas.run()
        dataset = meas.dataset
    
        if self.execution:
            if self.save_dir is not None:
                if self.want_while:
                    self.JOBID = None
                self.save_path = os.path.join(self.save_dir,f"zgateT1_{datetime.now().strftime('%Y%m%d%H%M%S') if self.JOBID is None else self.JOBID}")
                self.__raw_data_location = self.save_path + ".nc"
                dataset.to_netcdf(self.__raw_data_location)
                
            else:
                self.save_fig_path = None
        
    def CloseMeasurement(self):
        shut_down(self.cluster,self.Fctrl)


    def RunAnalysis(self, new_QD_path:str=None,new_file_path:str=None, time_dep_plot:bool=False):
        """ If new file path was given, check all the data in that folder. """
        
        if self.execution:
            if new_QD_path is None:
                QD_file = self.QD_path
            else:
                QD_file = new_QD_path

            if new_file_path is None:
                file_path = self.__raw_data_location
                fig_path = self.save_dir
            else:
                file_path = new_file_path
                fig_path = os.path.split(new_file_path)[0]

            QD_savior = QDmanager(QD_file)
            QD_savior.QD_loader()


            nc_paths = ZgateT1_dataReducer(fig_path)
            for q in nc_paths:
                if QD_savior.rotate_angle[q][0] != 0:
                    ref = QD_savior.rotate_angle[q]
                else:
                    eyeson_print(f"{q} rotation angle is 0, use contrast to analyze.")
                    ref = QD_savior.refIQ[q]

                ds = open_dataset(nc_paths[q])
                ANA = Multiplex_analyzer("auxA")
                ANA._import_data(ds,var_dimension=2,refIQ=ref)
                ANA._start_analysis(time_sort=time_dep_plot)
                ANA._export_result(nc_paths[q])
                ds.close()
            

    def WorkFlow(self, histo_counts:int=None):
        idx = 1
        start_time = datetime.now()
        while True:
            self.PrepareHardware()

            self.RunMeasurement()

            self.CloseMeasurement()  

            slightly_print(f"It's the {idx}-th measurement, about {round((datetime.now() - start_time).total_seconds()/60,1)} mins recorded.")
            
            if histo_counts is not None:
                # ensure the histo_counts you set is truly a number
                try: 
                    a = int(histo_counts)/100
                    self.want_while = True
                except:
                    raise TypeError(f"The arg `histo_counts` you set is not a number! We see it's {type(histo_counts)}...")
                if histo_counts == idx:
                    break
            idx += 1
            if not self.want_while:
                break
            
                
class QubitMonitor():
    def __init__(self, QD_path:str, save_dir:str, execution:bool=True):
        self.QD_path = QD_path
        self.save_dir = save_dir
        self.Execution = execution
        self.T1_max_evo_time:float = 100e-6
        self.T1_target_qs:list = []
        self.T2_max_evo_time:float = 100e-6
        self.T2_target_qs:list = []
        self.OS_target_qs:list = [] 
        self.echo_pi_num:list = [0]
        self.OSmode:bool = False
        self.time_sampling_func = 'linspace'
        self.time_ptsORstep:int|float = 100
        self.OS_shots:int = 10000
        self.AVG:int = 300
        self.idx = 0
        self.ramsey:bool = False
        self.echo:bool = False
        self.CPMG:bool = False


    
    def __decideT2series__(self):
        self.echo_pi_num = list(set(self.echo_pi_num)) # remove repeat elements
        
        if 0 in self.echo_pi_num:
            self.ramsey = True
            self.echo_pi_num.remove(0)
          
        if 1 in self.echo_pi_num:
            self.echo = True
            self.echo_pi_num.remove(1)
        
        if len(self.echo_pi_num) > 0 :
            self.CPMG = True
        

    def StartMonitoring(self):
        self.__decideT2series__()
        start_time = datetime.now()
        
        while True:
            if len(self.T1_target_qs) and self.T1_max_evo_time:
                eyeson_print("Measuring T1 ....")
                EXP = EnergyRelaxation(QD_path=self.QD_path,data_folder=self.save_dir)
                EXP.SetParameters(self.T1_max_evo_time,self.T1_target_qs,self.time_sampling_func,self.time_ptsORstep,1,self.AVG,self.Execution,self.OSmode)
                EXP.WorkFlow()

            if len(self.T2_target_qs) and self.T2_max_evo_time:
                if self.ramsey:
                    eyeson_print("Measuring T2* ....")
                    EXP = Ramsey(QD_path=self.QD_path,data_folder=self.save_dir)
                    EXP.sec_phase = 'y'
                    EXP.SetParameters(self.T2_max_evo_time,self.T2_target_qs,self.time_sampling_func,self.time_ptsORstep,1,self.AVG,self.Execution,self.OSmode)
                    EXP.WorkFlow()
                if self.echo:
                    eyeson_print("Measuring T2 ....")
                    EXP = SpinEcho(QD_path=self.QD_path,data_folder=self.save_dir)
                    EXP.SetParameters(self.T2_max_evo_time,self.T2_target_qs,self.time_sampling_func,self.time_ptsORstep,1,self.AVG,self.Execution,self.OSmode)
                    EXP.WorkFlow()
                if self.CPMG:
                    for pi_num in self.echo_pi_num:
                        eyeson_print(f"Doing CPMG for {pi_num} pi-pulses inside ....")
                        EXP = CPMG(QD_path=self.QD_path,data_folder=self.save_dir)
                        EXP.SetParameters(self.T2_max_evo_time,self.T2_target_qs,pi_num,self.time_sampling_func,self.time_ptsORstep,1,self.AVG,self.Execution,self.OSmode)
                        EXP.WorkFlow()

            if self.OS_target_qs is not None:
                if  self.OS_shots != 0:
                    if len(self.OS_target_qs) == 0:
                        self.OS_target_qs = list(set(self.T1_target_qs+self.T2_target_qs))
                    eyeson_print("Measuring Effective temperature .... ")
                    EXP = nSingleShot(QD_path=self.QD_path,data_folder=self.save_dir)
                    EXP.SetParameters(self.OS_target_qs,1,self.OS_shots,self.Execution)
                    EXP.WorkFlow()
            slightly_print(f"It's the {self.idx}-th measurement, about {round((datetime.now() - start_time).total_seconds()/3600,2)} hrs recorded.")
            self.idx += 1

    def TimeMonitor_analysis(self,New_QD_path:str=None,New_data_file:str=None,save_all_fit_fig:bool=False):
        # if New_QD_path is not None:
        #     self.QD_path = New_QD_path
        # if New_data_file is not None:
        #     self.save_dir = os.path.split(New_data_file)[0]

        # QD_agent = QDmanager(self.QD_path)
        # QD_agent.QD_loader()
        ## to avoid circular import
        ## From qblox_drive_AS.analysis.TimeTraceAna import time_monitor_data_ana
        #  time_monitor_data_ana(QD_agent,self.save_dir,save_all_fit_fig)
        raise BufferError("Please go `qblox_drive_AS.analysis.TimeTraceAna` analyzing the data by `time_monitor_data_ana()`. ")


class DragCali(ExpGovernment):
    def __init__(self,QD_path:str,data_folder:str=None,JOBID:str=None):
        super().__init__()
        self.QD_path = QD_path
        self.save_dir = data_folder
        self.__raw_data_location:str = ""
        self.JOBID = JOBID

    @property
    def RawDataPath(self):
        return self.__raw_data_location

    def SetParameters(self, drag_coef_range:list ,target_qs:list, coef_sampling_funct:str, coef_ptsORstep:int=100, avg_n:int=100, execution:bool=True, OSmode:bool=False)->None:
        """ ### Args:
            * drag_coef_range: [-2, 2]\n
            * target_qs: ["q0", "q1"]\n
            * coef_sampling_funct: str, `linspace` or `arange`.\n
        """
        if coef_sampling_funct in ['linspace','logspace','arange']:
            sampling_func:callable = eval(coef_sampling_funct)
        else:
            raise ValueError(f"Can't recognize the given sampling function name = {coef_sampling_funct}")
        
        self.drag_coef_samples = {}
        for q in sort_dict_with_qidx(target_qs):
           self.drag_coef_samples[q] = sampling_func(*drag_coef_range,coef_ptsORstep)
        self.avg_n = avg_n
        self.execution = execution
        self.OSmode = OSmode
        self.target_qs = sort_dict_with_qidx(target_qs)
        

    def PrepareHardware(self):
        self.QD_agent, self.cluster, self.meas_ctrl, self.ic, self.Fctrl = init_meas(QuantumDevice_path=self.QD_path)
        # bias coupler
        self.Fctrl = coupler_zctrl(self.Fctrl,self.QD_agent.Fluxmanager.build_Cctrl_instructions([cp for cp in self.Fctrl if cp[0]=='c' or cp[:2]=='qc'],'i'))
        # offset bias, LO and atte
        for q in self.target_qs:
            self.Fctrl[q](self.QD_agent.Fluxmanager.get_proper_zbiasFor(target_q=q))
            IF_minus = self.QD_agent.Notewriter.get_xyIFFor(q)
            xyf = self.QD_agent.quantum_device.get_element(q).clock_freqs.f01()
            set_LO_frequency(self.QD_agent.quantum_device,q=q,module_type='drive',LO_frequency=xyf-IF_minus)
            init_system_atte(self.QD_agent.quantum_device,[q],ro_out_att=self.QD_agent.Notewriter.get_DigiAtteFor(q, 'ro'), xy_out_att=self.QD_agent.Notewriter.get_DigiAtteFor(q,'xy'))

        
    def RunMeasurement(self):
        from qblox_drive_AS.Calibration_exp.DRAGcali import DRAGcalibrationPS 
        meas = DRAGcalibrationPS()
        meas.ro_elements = self.drag_coef_samples
        meas.execution = self.execution
        meas.n_avg = self.avg_n
        meas.meas_ctrl = self.meas_ctrl
        meas.QD_agent = self.QD_agent
        meas.run()
        dataset = meas.dataset
    
        
        if self.execution:
            if self.save_dir is not None:
                self.save_path = os.path.join(self.save_dir,f"DragCali_{datetime.now().strftime('%Y%m%d%H%M%S') if self.JOBID is None else self.JOBID}")
                self.__raw_data_location = self.save_path + ".nc"
                dataset.to_netcdf(self.__raw_data_location)
                
            else:
                self.save_fig_path = None
        
    def CloseMeasurement(self):
        shut_down(self.cluster,self.Fctrl)


    def RunAnalysis(self,new_QD_path:str=None,new_file_path:str=None):
        """ User callable analysis function pack """
        
        if self.execution:
            if new_QD_path is None:
                QD_file = self.QD_path
            else:
                QD_file = new_QD_path

            if new_file_path is None:
                file_path = self.__raw_data_location
                fig_path = self.save_dir
            else:
                file_path = new_file_path
                fig_path = os.path.split(new_file_path)[0]

            QD_savior = QDmanager(QD_file)
            QD_savior.QD_loader()

            ds = open_dataset(file_path)
            answer = {}
            for var in ds.data_vars:
                if var.split("_")[-1] != 'dragcoef':
                    if QD_savior.rotate_angle[var][0] != 0:
                        ref = QD_savior.rotate_angle[var]
                    else:
                        eyeson_print(f"{var} rotation angle is 0, use contrast to analyze.")
                        ref = QD_savior.refIQ[var]
                    ANA = Multiplex_analyzer("c6")
                    ANA._import_data(ds,var_dimension=1,refIQ=ref)
                    ANA._start_analysis(var_name = var)
                    ANA._export_result(fig_path)
                    answer[var] = ANA.fit_packs
            
            ds.close()

            permi = mark_input(f"What qubit can be updated ? {list(answer.keys())}/ all/ no ").lower()
            
            if permi in list(answer.keys()):
                q_element:BasicTransmonElement = QD_savior.quantum_device.get_element(permi)
                q_element.rxy.motzoi(float(answer[permi]["optimal_drag_coef"]))
                QD_savior.QD_keeper()
            elif permi in ["all",'y','yes']:
                for q in answer:
                    q_element:BasicTransmonElement = QD_savior.quantum_device.get_element(q)
                    q_element.rxy.motzoi(float(answer[q]["optimal_drag_coef"]))
                QD_savior.QD_keeper()
            else:
                print("Updating got denied ~")

    def WorkFlow(self):
        
        self.PrepareHardware()

        self.RunMeasurement()

        self.CloseMeasurement() 


class XGateErrorTest(ExpGovernment):
    """ Helps you get the **Dressed** cavities. """
    def __init__(self,QD_path:str,data_folder:str=None,JOBID:str=None):
        super().__init__()
        self.QD_path = QD_path
        self.save_dir = data_folder
        self.__raw_data_location:str = ""
        self.JOBID = JOBID

    @property
    def RawDataPath(self):
        return self.__raw_data_location
    
    @RawDataPath.setter
    def RawDataPath(self,path:str):
        self.__raw_data_location = path

    def SetParameters(self, target_qs:list, shots:int=10000, MaxGate_num:int=300, execution:bool=True, use_untrained_wf:bool=False):
        """ 
        ### Args:\n
        * target_qs: list, like ["q0", "q1", ...]
        """
        self.use_time_label:bool = False
        self.avg_n = shots
        self.Max_Gate_num = MaxGate_num
        self.execution = execution
        self.use_de4t_wf = use_untrained_wf
        self.target_qs = sort_dict_with_qidx(target_qs)
        



    def PrepareHardware(self):
        self.QD_agent, self.cluster, self.meas_ctrl, self.ic, self.Fctrl = init_meas(QuantumDevice_path=self.QD_path)
        # bias coupler
        self.Fctrl = coupler_zctrl(self.Fctrl,self.QD_agent.Fluxmanager.build_Cctrl_instructions([cp for cp in self.Fctrl if cp[0]=='c' or cp[:2]=='qc'],'i'))
        # offset bias, LO and driving atte
        for q in self.target_qs:
            self.Fctrl[q](self.QD_agent.Fluxmanager.get_proper_zbiasFor(target_q=q))
            IF_minus = self.QD_agent.Notewriter.get_xyIFFor(q)
            xyf = self.QD_agent.quantum_device.get_element(q).clock_freqs.f01()
            set_LO_frequency(self.QD_agent.quantum_device,q=q,module_type='drive',LO_frequency=xyf-IF_minus)
            init_system_atte(self.QD_agent.quantum_device,[q],ro_out_att=self.QD_agent.Notewriter.get_DigiAtteFor(q, 'ro'), xy_out_att=self.QD_agent.Notewriter.get_DigiAtteFor(q,'xy'))
        
    
    def RunMeasurement(self):
        from qblox_drive_AS.aux_measurement.GateErrorTest import XGateError_single_shot
       

        dataset = XGateError_single_shot(self.QD_agent,self.target_qs,self.Max_Gate_num,self.avg_n,self.use_de4t_wf,self.execution)
        if self.execution:
            if self.save_dir is not None:
                self.save_path = os.path.join(self.save_dir,f"XGateErrorTest_{datetime.now().strftime('%Y%m%d%H%M%S') if (self.JOBID is None or self.use_time_label) else self.JOBID}")
                self.__raw_data_location = self.save_path + ".nc"
                dataset.to_netcdf(self.__raw_data_location)
            else:
                self.save_fig_path = None
        
    def CloseMeasurement(self):
        shut_down(self.cluster,self.Fctrl)


    def RunAnalysis(self,new_QD_path:str=None,new_file_path:str=None):
        """ if histo_ana, it will check all the data in the same folder with the given new_file_path """
    
        if self.execution:
            if new_QD_path is None:
                QD_file = self.QD_path
            else:
                QD_file = new_QD_path

            if new_file_path is None:
                file_path = self.__raw_data_location
                fig_path = self.save_dir
            else:
                file_path = new_file_path
                fig_path = os.path.split(new_file_path)[0]

            QD_savior = QDmanager(QD_file)
            QD_savior.QD_loader()

            
            ds = open_dataset(file_path)
            answer = {}
            for var in ds.data_vars:
                ANA = Multiplex_analyzer("t1")
                ANA._import_data(ds,var_dimension=0,fq_Hz=QD_savior.quantum_device.get_element(var).clock_freqs.f01())
                ANA._start_analysis(var_name=var)
                pic_path = os.path.join(fig_path,f"{var}_XGateErrorTest_{datetime.now().strftime('%Y%m%d%H%M%S') if self.JOBID is None else self.JOBID}")
                ANA._export_result(pic_path)

                answer[var] = ANA.fit_packs 
                highlight_print(f"{var} X-gate phase error ~ {round(answer[var]['f'], 3)} mrad")
                
            ds.close()

    def WorkFlow(self):
        
        self.PrepareHardware()

        self.RunMeasurement()

        self.CloseMeasurement() 

class ParitySwitch(ExpGovernment):
    def __init__(self,QD_path:str,data_folder:str=None,JOBID:str=None):
        super().__init__()
        self.QD_path = QD_path
        self.save_dir = data_folder
        self.__raw_data_location:str = ""
        self.JOBID = JOBID
        self.histos:int = 0
        self.execution = False  # 預設值，避免未定義錯誤

    @property
    def RawDataPath(self):
        return self.__raw_data_location

    def SetParameters(self, time_range:dict, histo_counts:int=1, avg_n:int=100, execution:bool=True, OSmode:bool=False)->None:
        """ ### Args:
            * time_range: {"q0":500e-9, ...}\n
            * histo_counts: int, larger than 100 use while loop.\n
        """
        from qblox_drive_AS.SOP.RabiOsci import sort_elements_2_multiples_of
        

        self.time_samples = {}
        for q in sort_dict_with_qidx(time_range):
            self.time_samples[q] = sort_elements_2_multiples_of(array([time_range[q]])*1e9,4)*1e-9
            
        self.avg_n = avg_n
        # raise TimeoutError()

        if histo_counts <= 200:
            self.want_while = False
            self.histos = histo_counts
        else:
            self.want_while = True
            self.histos = 1
        
        self.execution = execution
        self.OSmode = OSmode
        self.spin_num = {}
        self.target_qs = sort_dict_with_qidx(list(time_range.keys()))

        # FPGA memory limit guard
        if self.OSmode:
            for q in self.time_samples:
                if self.avg_n * self.time_samples[q].shape[0] > 131000:
                    raise MemoryError(f"Due to Qblox FPGA memory limit, time_pts * shots must be less than 131000. And you are trying to set {self.avg_n * self.time_samples[q].shape[0]} for {q}")
        
        

    def PrepareHardware(self):
        self.QD_agent, self.cluster, self.meas_ctrl, self.ic, self.Fctrl = init_meas(QuantumDevice_path=self.QD_path)
        # bias coupler
        self.Fctrl = coupler_zctrl(self.Fctrl,self.QD_agent.Fluxmanager.build_Cctrl_instructions([cp for cp in self.Fctrl if cp[0]=='c' or cp[:2]=='qc'],'i'))
        # offset bias, LO and atte
        for q in self.target_qs:
            self.Fctrl[q](self.QD_agent.Fluxmanager.get_proper_zbiasFor(target_q=q))
            IF_minus = self.QD_agent.Notewriter.get_xyIFFor(q)
            slightly_print(f"{q} arti-detune = {round(self.QD_agent.Notewriter.get_artiT2DetuneFor(q)*1e-6,2)} MHz")
            xyf = self.QD_agent.quantum_device.get_element(q).clock_freqs.f01()+self.QD_agent.Notewriter.get_artiT2DetuneFor(q)
            self.QD_agent.quantum_device.get_element(q).clock_freqs.f01(xyf)
            set_LO_frequency(self.QD_agent.quantum_device,q=q,module_type='drive',LO_frequency=xyf-IF_minus)
            init_system_atte(self.QD_agent.quantum_device,[q],ro_out_att=self.QD_agent.Notewriter.get_DigiAtteFor(q, 'ro'), xy_out_att=self.QD_agent.Notewriter.get_DigiAtteFor(q,'xy'))
        
    def RunMeasurement(self):
        from qblox_drive_AS.SOP.T2 import RamseyT2PS
        meas = RamseyT2PS()
        meas.set_time_samples = self.time_samples
        meas.set_os_mode = self.OSmode
        meas.set_n_avg = self.avg_n
        meas.set_repeat = self.histos
        meas.set_spin_num = self.spin_num
        meas.set_second_phase = 'x'
        meas.meas_ctrl = self.meas_ctrl
        meas.QD_agent = self.QD_agent
        meas.execution = self.execution
        
        meas.run()
        dataset = meas.dataset


        # dataset = Ramsey(self.QD_agent,self.meas_ctrl,self.time_samples,self.spin_num,self.histos,self.avg_n,self.execution)
        if self.execution:
            if self.save_dir is not None:
                self.save_path = os.path.join(self.save_dir,f"ParitySwitch_{datetime.now().strftime('%Y%m%d%H%M%S') if self.JOBID is None else self.JOBID}")
                self.__raw_data_location = self.save_path + ".nc"
                dataset.to_netcdf(self.__raw_data_location)
                
            else:
                self.save_fig_path = None
        
    def CloseMeasurement(self):
        shut_down(self.cluster,self.Fctrl)


    def RunAnalysis(self,new_QD_path:str=None,new_file_path:str=None,new_QDagent:QDmanager=None,new_pic_save_place:str=None):
        """ User callable analysis function pack """
        
        if self.execution:
            if new_QD_path is None:
                QD_file = self.QD_path
            else:
                QD_file = new_QD_path

            if new_file_path is None:
                file_path = self.__raw_data_location
                fig_path = self.save_dir
            else:
                file_path = new_file_path
                fig_path = os.path.split(new_file_path)[0]

            if new_QDagent is None:
                QD_savior = QDmanager(QD_file)
                QD_savior.QD_loader()
            else:
                QD_savior = new_QDagent

            if new_pic_save_place is not None:
                fig_path = new_pic_save_place

            ds = open_dataset(file_path)
            md = None
            
            for var in ds.data_vars:
                if var.split("_")[-1] != 'x':
                    self.ANA = Multiplex_analyzer("a3")
                    if ds.attrs['method'].lower() in ["shot", "oneshot"]:
                        md = QD_savior.StateDiscriminator.summon_discriminator(var)
                    if QD_savior.rotate_angle[var][0] != 0:
                        ref = QD_savior.rotate_angle[var]
                    else:
                        eyeson_print(f"{var} rotation angle is 0, use contrast to analyze.")
                        ref = QD_savior.refIQ[var]
                    self.ANA._import_data(ds,var_dimension=2,refIQ=ref)

                    q_infor = QD_savior.quantum_device.get_element(var)
                    
                    self.ANA._start_analysis(var_name=var, OSmodel=md, t_interval = q_infor.measure.integration_time() + q_infor.reset.duration())
                    if self.save_pics:
                        self.ANA._export_result(fig_path)
     
        ds.close()
        if self.keep_QD:
            QD_savior.QD_keeper()
            

    def WorkFlow(self,freq_detune_Hz:float=None):
        while True:
            self.PrepareHardware()

            if freq_detune_Hz is not None:
                for q in self.target_qs:
                    self.QD_agent.quantum_device.get_element(q).clock_freqs.f01(self.QD_agent.quantum_device.get_element(q).clock_freqs.f01()+freq_detune_Hz)

            self.RunMeasurement()

            self.CloseMeasurement()   
            if not self.want_while:
                break


if __name__ == "__main__":
    EXP = nSingleShot("")
    EXP.execution = True
    EXP.histos = 1
    EXP.RunAnalysis(new_QD_path="qblox_drive_AS/QD_backup/20250411/DR4#81_SumInfo.pkl", new_file_path="qblox_drive_AS/Meas_raw/20250410/H17M45S50/SingleShot_20250410174614.nc")

    