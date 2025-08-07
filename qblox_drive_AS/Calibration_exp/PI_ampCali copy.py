"""This program includes PowerRabi and TimeRabi. When it's PoweRabi, default ctrl pulse duration is 20ns."""
from qblox_drive_AS.support.UserFriend import *
from qcodes.parameters import ManualParameter
from xarray import Dataset
from numpy import array, arange
from qblox_drive_AS.support import Data_manager, BasicTransmonElement
from quantify_scheduler.gettables import ScheduleGettable
from qblox_drive_AS.support import check_acq_channels
from qblox_drive_AS.support.Pulser import ScheduleConductor
from qblox_drive_AS.support.Pulse_schedule_library import BinMode, Schedule, pulse_preview, X, Reset, IdlePulse, Measure

class TomoXXgateerrorSS(ScheduleConductor):
    def __init__(self):
        super().__init__()
        self._ro_elements:dict = {}
        self.gate_num:int
        self.n_avg:int
        self.initial:str
    
    @property
    def ro_elements(self):
        return self._ro_elements
    @ro_elements.setter
    def ro_elements(self, ro_eles:dict):
        self._ro_elements = ro_eles
    @property
    def gate_num(self):
        return self.gate_num
    @gate_num.setter
    def gate_num(self, num:int):
        self.gate_num = num
    @property
    def n_avg(self):
        return self._avg_n
    @n_avg.setter
    def n_avg(self, avg:int):
        self._avg_n = avg
    @property
    def initial(self):
        return self.initial
    @initial.setter
    def initial(self, initial_state):
        self.initial = initial_state
    

    def __PulseSchedule__(self, 
        new_pi_amp:dict,
        gate_num:int,
        repetitions:int=1,
    )-> Schedule:
        qubits2read = list(new_pi_amp.keys())
        sched = Schedule("Pi amp modification", repetitions=repetitions)

        for acq_idx in range(array(new_pi_amp[qubits2read[0]]).shape[0]):
            sched.add(Reset(*qubits2read))
            for q in qubits2read:
                new_amp180 = new_pi_amp[q][acq_idx]
        
                for pi_num in range(gate_num):
                    for pi_idx in range(2):
                        pi = sched.add(X(q, amp180=new_amp180))

            sched.add(Measure(*qubits2read, acq_index=acq_idx, acq_protocol="SSBIntegrationComplex", bin_mode=BinMode.AVERAGE))
                        
        self.schedule =  sched  
        return sched
        
    def __SetParameters__(self, *args, **kwargs):
         
        self.__datapoint_idx = arange(len(list(list(self._ro_elements.values())[0])))
        self.__amp180_samples = {}
        
        for q in self._ro_elements:
            qubit_info:BasicTransmonElement = self.QD_agent.quantum_device.get_element(q)
            self.__amp180_samples[q] = qubit_info.rxy.amp180() * self._ro_elements[q] 
            eyeson_print(f"{q} Reset time: {round(qubit_info.reset.duration()*1e6,0)} µs")
           
        self.__amp180 = ManualParameter(name="amp180", unit="V", label="amplitude")
        self.__amp180.batched = True
        self.__gate =  ManualParameter(name="gate_num", unit="", label="number")
        self.__gate.batched = False


        self.QD_agent = check_acq_channels(self.QD_agent, list(self._ro_elements.keys()))
        self.__spec_sched_kwargs = dict(   
        new_pi_amp=self.__amp180_samples,
        gate_num=self.__gate,
        )

    def __Compose__(self, *args, **kwargs):
        
        if self._execution:
            self.gate_num.insert(0,1)  # start with 0 pi number to avoid bugs 
            print(self.gate_num)
            self.__gettable = ScheduleGettable(
            self.QD_agent.quantum_device,
            schedule_function=self.__PulseSchedule__, 
            schedule_kwargs=self.__spec_sched_kwargs,
            real_imag=True,
            batched=True,
            num_channels=len(list(self._ro_elements.keys())),
            )
            self.QD_agent.quantum_device.cfg_sched_repetitions(self._avg_n)
            self.meas_ctrl.gettables(self.__gettable)
            self.meas_ctrl.settables([self.__amp180, self.__gate])
            self.meas_ctrl.setpoints_grid([self.__datapoint_idx, self.gate_num])
        
        else:
            preview_para = {}
            for q in self.__amp180_samples:
                preview_para[q] = array([self.__amp180_samples[q][1], self.__amp180_samples[q][-2]])
            self.__spec_sched_kwargs['new_pi_amp']= preview_para
            self.__spec_sched_kwargs['gate_num']= self.gate_num[0]
        

    def __RunAndGet__(self, *args, **kwargs):
        
        if self._execution:
            rs_ds = self.meas_ctrl.run("pi-amp calibration")
            dict_ = {}
            for q_idx, q in enumerate(list(self._ro_elements.keys())):
                coefs = 2*len(self.gate_num)*list(self._ro_elements[q])
                i_data = array(rs_ds[f'y{2*q_idx}']).reshape(len(self.gate_num),self.__datapoint_idx.shape[0])
                q_data = array(rs_ds[f'y{2*q_idx+1}']).reshape(len(self.gate_num),self.__datapoint_idx.shape[0])
                dict_[q] = (["mixer", "PiPairNum", "PiAmpCoef"],array([i_data,q_data]))
                dict_[f'{q}_PIcoef'] = (["mixer", "PiPairNum", "PiAmpCoef"],array(coefs).reshape(2,len(self.gate_num),self.__datapoint_idx.shape[0]))

            ds = Dataset(dict_,coords={"mixer":array(["I","Q"]),"PiPairNum":array(self.gate_num),"PiAmpCoef":self.__datapoint_idx})
            
            ds.attrs["execution_time"] = Data_manager().get_time_now()
            ds.attrs["method"] = "Average"
            ds.attrs["system"] = "qblox"
            self.dataset = ds
        
        else:
            pulse_preview(self.QD_agent.quantum_device,self.__PulseSchedule__,self.__spec_sched_kwargs)


    

