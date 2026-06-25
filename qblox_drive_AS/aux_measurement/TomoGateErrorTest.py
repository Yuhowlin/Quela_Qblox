from qblox_drive_AS.support.Pulser import ScheduleConductor
from qblox_drive_AS.support.Pulse_schedule_library import Schedule, X, Reset, Rxy, Measure, BinMode, IdlePulse
from qblox_drive_AS.support.UserFriend import eyeson_print
from qblox_drive_AS.support import check_acq_channels
from qcodes.parameters import ManualParameter
from numpy import arange, array
from xarray import Dataset
from quantify_scheduler.gettables import ScheduleGettable
from qblox_drive_AS.support import Data_manager
from qblox_drive_AS.support.Pulse_schedule_library import pulse_preview
from qblox_drive_AS.support import BasicTransmonElement
from qcodes.parameters import ManualParameter
from itertools import product
import numpy as np
class XTomographyPS(ScheduleConductor):
    def __init__(self):
        super().__init__()
        self._target_q: list = ["q0"]
        self._init_state: str = "zero"  # options: "zero", "plus", "plus_i"
        self._gate_counts:list = arange(0, 100)  # 1~99 X gates
        self._avg_n:int = 100
        self._control_q: str = "q0"
        self._noise_q: str = "q0"

    @property
    def target_q(self):
        return self._target_q

    @target_q.setter
    def target_q(self, q: list):
        self._target_q = q

    @property
    def initial_state(self):
        return self._init_state

    @initial_state.setter
    def initial_state(self, state: str):
        if state not in ["zero", "plus", "plus_i"]:
            raise ValueError("initial_state must be one of: 'zero', 'plus', 'plus_i'")
        self._init_state = state

    @property
    def n_avg(self):
        return self._avg_n
    @n_avg.setter
    def n_avg(self, avg:int):
        self._avg_n = avg

    @property
    def control_q(self):
        return self._control_q

    @control_q.setter
    def control_q(self, qt: str):
        self._control_q = qt

    @property
    def noise_q(self):
        return self._noise_q

    @noise_q.setter
    def noise_q(self, qn: str):
        self._noise_q = qn


    def __PulseSchedule__(self,
        gate_counts: list,
        repetitions: int = 1
    ) -> Schedule:

        sched = Schedule("X-gate tomography", repetitions=repetitions)
        q = self._target_q
            
        
        for acq_idx, x_gate_count in enumerate(gate_counts):
            for basis in ['X', 'Y', 'Z']:
                reset = sched.add(Reset(*self._target_q))
                for q in self._target_q:
                # Prepare initial state
                    if self._init_state == "plus" and x_gate_count >=2 :
                        last_op = sched.add(Rxy(theta=90.0, phi=0, qubit=q), ref_op=reset)  # H gate ≈ Rx(pi/2)
                    elif self._init_state == "plus_i"and x_gate_count >=2 :
                        last_op = sched.add(Rxy(theta=90.0, phi=90.0, qubit=q), ref_op=reset)
                    else:
                        last_op = reset
                    # X gates3
                    for _ in range(x_gate_count):
                        # 1. 先加入 control_q 的 X gate，並把這個動作存成一個變數 (reference)
                        control_op = sched.add(X(self._control_q))
                        
                        # 2. 加入 noise_q 的 X gate，強制它的「起點」對齊 control_op 的「起點」
                        if self._noise_q == None:
                            pass
                        else:
                            sched.add(X(self._noise_q), 
                                    ref_op=control_op, 
                                    ref_pt="start", 
                                    ref_pt_new="start"
                                    )
                        last_op = control_op
                # Tomography: X, Y, Z bases
                    buffer_time = 60e-9  # 設定你想要的緩衝時間，例如 50 ns (單位為秒)
                
                # Tomography: X, Y, Z bases
                    if basis == 'X':
                        # 在 last_op 結束後，等待 buffer_time 再打 Rxy
                        tomo_op = sched.add(Rxy(theta=90.0, phi=90.0, qubit=q), 
                                            ref_op=last_op, 
                                            rel_time=buffer_time)
                        meas_ref_op = tomo_op
                        meas_rel_time = 0.0 # Measure 緊接在 tomo_op 後面
                        
                    elif basis == 'Y':
                        tomo_op = sched.add(Rxy(theta=-90.0, phi=0, qubit=q), 
                                            ref_op=last_op, 
                                            rel_time=buffer_time)
                        meas_ref_op = tomo_op
                        meas_rel_time = 0.0 # Measure 緊接在 tomo_op 後面
                        
                    else: # basis == 'Z'
                        # Z basis 沒有 tomo_op，所以 Measure 直接以 last_op 為參考，並加入緩衝時間
                        meas_ref_op = last_op
                        meas_rel_time = buffer_time

                    # 加 Measure
                    sched.add(Measure(q,
                                    acq_index=acq_idx * 3 + ['X', 'Y', 'Z'].index(basis),
                                    acq_protocol="SSBIntegrationComplex",
                                    bin_mode=BinMode.APPEND),
                            ref_op=meas_ref_op,
                            rel_time=meas_rel_time)

        return sched


    def __SetParameters__(self, *args, **kwargs):    
        self.__x_gate_count = ManualParameter(name="X_gate_count", unit="#", label="Number of X gates")
        self.__x_gate_count.batched = True
        self.basis = ["X", "Y", "Z"]
        self.QD_agent = check_acq_channels(self.QD_agent, self._target_q)

        self.__sched_kwargs = dict(
            gate_counts=self._gate_counts
        )

    def __Compose__(self, *args, **kwargs):
        if self._execution:
            self.__gettable = ScheduleGettable(
                self.QD_agent.quantum_device,
                schedule_function=self.__PulseSchedule__,
                schedule_kwargs=self.__sched_kwargs,
                real_imag=True,
                batched=True,
                num_channels=1
            )
            self.QD_agent.quantum_device.cfg_sched_repetitions(self._avg_n)
            self.meas_ctrl.gettables(self.__gettable)
            self.meas_ctrl.settables([self.__x_gate_count])
            gate_counts = self._gate_counts
            basis_labels = self.basis
            shots = self._avg_n

            gate_grid, basis_grid, shot_grid = np.meshgrid(gate_counts, basis_labels, arange(shots), indexing="ij")

            self.meas_ctrl.setpoints_grid((
                
                basis_grid.flatten(),
                gate_grid.flatten(),
                shot_grid.flatten(),
            ))


        else:
            self.__sched_kwargs['gate_counts'] = [0, 1, 2]  # preview 3 points only

    def __RunAndGet__(self, *args, **kwargs):
        if self._execution:
            rs_ds = self.meas_ctrl.run("X tomography")
            ds = Dataset()

            # ✅ 確保 target_q 是 string
            target_q = self._target_q[0] if isinstance(self._target_q, list) else self._target_q

            gate_len = len(self._gate_counts)
            shots = self._avg_n
            # reshape 成 (pulse_num, basis, index)
            i_data = array(rs_ds["y0"]).reshape(shots, gate_len, 3)
            q_data = array(rs_ds["y1"]).reshape(shots, gate_len, 3)

            # ✅ 設定座標
            ds.coords["index"] = arange(shots)
            ds.coords["pulse_num"] = self._gate_counts
            ds.coords["mixer"] = ["I", "Q"]

            basis_labels = ["x", "y", "z"]
            for basis_idx, basis in enumerate(basis_labels):
                # 取出 shape: (shots, pulse_num)
                i_part = i_data[:, :, basis_idx]
                q_part = q_data[:, :, basis_idx]

                # 轉成 (pulse_num, index)
                i_part = i_part.T
                q_part = q_part.T

                # 再加 mixer 維度 → (mixer, pulse_num, index)
                full_data = array([i_part, q_part])

                var_name = f"{target_q}_{basis}"
                ds[var_name] = (["mixer", "pulse_num", "index"], full_data)
            # ✅ 附加 metadata
            ds.attrs["execution_time"] = Data_manager().get_time_now()
            ds.attrs["bases"] = "x,y,z"
            ds.attrs["system"] = "qblox"
            ds.attrs["method"] = "Average"

            self.dataset = ds


        else:
            pulse_preview(self.QD_agent.quantum_device, self.__PulseSchedule__, self.__sched_kwargs)



from qblox_drive_AS.support.Pulser import ScheduleConductor
from qblox_drive_AS.support.Pulse_schedule_library import Schedule, X, Reset, Rxy, Measure, BinMode
from qblox_drive_AS.support import check_acq_channels
from qcodes.parameters import ManualParameter
from numpy import arange, array
from xarray import Dataset
from quantify_scheduler.gettables import ScheduleGettable
from qblox_drive_AS.support import Data_manager
from qblox_drive_AS.support.Pulse_schedule_library import pulse_preview
import numpy as np

class AdvancedTomographyPS(ScheduleConductor):
    def __init__(self):
        super().__init__()
        self.target_q: list = ["q0"]
        self.qubit_configs: dict = {}
        self.symmetrized_readout: bool = True
        self.current_gate_count: int = 0
        self.avg_n: int = 100
        self.run_mode: str = "tomography" 

    def _add_concurrent_ops(self, sched, ops_dict, last_ref):
        """ 
        確保所有 qubit 的操作在同一時間點同時發生的核心排程器 
        ops_dict: {qubit_name: Operation_Object}
        """
        if not ops_dict: # 如果該 step 沒有任何 qubit 需要操作 (例如全是 Idle)，直接回傳上一個參考點
            return last_ref
            
        first_op = None
        for q, op in ops_dict.items():
            if first_op is None:
                # 第一個 Qubit 的操作，接在「上一個動作」的尾巴 (end)
                first_op = sched.add(op, ref_op=last_ref, ref_pt="end")
            else:
                # 其餘 Qubit 的操作，對齊第一個 Qubit 操作的「起點」 (start)
                sched.add(op, ref_op=first_op, ref_pt="start")
                
        # 回傳這組平行操作，作為下一個步驟的參考點
        return first_op 

    def __PulseSchedule__(self, current_gate_count: int = 0, repetitions: int = 1) -> Schedule:
        sched = Schedule("Advanced Tomography", repetitions=repetitions)

        if self.run_mode == "training":
            # ==========================================
            # 模式 A: 只做 0, 1 State Training
            # ==========================================
            reset0 = sched.add(Reset(*self.target_q))
            sched.add(Measure(*self.target_q, acq_index=0, acq_protocol="SSBIntegrationComplex", bin_mode=BinMode.APPEND), ref_op=reset0, ref_pt="end")
            
            reset1 = sched.add(Reset(*self.target_q))
            ops_x = {q: X(q) for q in self.target_q}
            last_ref = self._add_concurrent_ops(sched, ops_x, reset1)
            sched.add(Measure(*self.target_q, acq_index=1, acq_protocol="SSBIntegrationComplex", bin_mode=BinMode.APPEND), ref_op=last_ref, ref_pt="end")
            
            return sched

        elif self.run_mode == "tomography":
            # ==========================================
            # 模式 B: 執行 Tomography 主序列 (嚴格對齊時間軸)
            # ==========================================
            for b_idx, basis in enumerate(['X', 'Y', 'Z']):
                
                # --- (A) Regular Readout ---
                last_ref = sched.add(Reset(*self.target_q))
                last_ref = self._apply_init_state(sched, last_ref)
                last_ref = self._apply_target_gates(sched, current_gate_count, last_ref)
                last_ref = self._apply_basis_rot(sched, basis, last_ref)
                
                reg_idx = b_idx * (2 if self.symmetrized_readout else 1)
                sched.add(Measure(*self.target_q, acq_index=reg_idx, acq_protocol="SSBIntegrationComplex", bin_mode=BinMode.APPEND), ref_op=last_ref, ref_pt="end")

                # --- (B) Symmetrized Inverted Readout ---
                if self.symmetrized_readout:
                    last_ref = sched.add(Reset(*self.target_q))
                    last_ref = self._apply_init_state(sched, last_ref)
                    last_ref = self._apply_target_gates(sched, current_gate_count, last_ref)
                    last_ref = self._apply_basis_rot(sched, basis, last_ref)
                    
                    ops_inv = {q: X(q) for q in self.target_q}
                    last_ref = self._add_concurrent_ops(sched, ops_inv, last_ref)
                        
                    inv_idx = reg_idx + 1
                    sched.add(Measure(*self.target_q, acq_index=inv_idx, acq_protocol="SSBIntegrationComplex", bin_mode=BinMode.APPEND), ref_op=last_ref, ref_pt="end")

            return sched

    # --- 以下皆改用字典收集操作，統一交給平行排程器處理 ---
    def _apply_init_state(self, sched, last_ref):
        ops = {}
        for q in self.target_q:
            state = self.qubit_configs[q]["init_state"]
            if state == '1': ops[q] = X(q)
            elif state == '+': ops[q] = Rxy(theta=90.0, phi=90.0, qubit=q)
            elif state == '-': ops[q] = Rxy(theta=-90.0, phi=90.0, qubit=q)
            elif state == '+i': ops[q] = Rxy(theta=-90.0, phi=0.0, qubit=q)
            elif state == '-i': ops[q] = Rxy(theta=90.0, phi=0.0, qubit=q)
        return self._add_concurrent_ops(sched, ops, last_ref)

    def _apply_target_gates(self, sched, gate_count, last_ref):
        for _ in range(gate_count):
            ops = {}
            for q in self.target_q:
                gate = self.qubit_configs[q]["target_gate"]
                if gate == 'X': ops[q] = X(q)
                elif gate == 'X90': ops[q] = Rxy(theta=90.0, phi=0.0, qubit=q)
                elif gate == 'Y': ops[q] = Rxy(theta=180.0, phi=90.0, qubit=q)
                elif gate == 'Y90': ops[q] = Rxy(theta=90.0, phi=90.0, qubit=q)
                # 'I' gate 不加入 ops 字典，等同於留白等待
            last_ref = self._add_concurrent_ops(sched, ops, last_ref)
        return last_ref

    def _apply_basis_rot(self, sched, basis, last_ref):
        ops = {}
        for q in self.target_q:
            if basis == 'X': ops[q] = Rxy(theta=90.0, phi=90.0, qubit=q)
            elif basis == 'Y': ops[q] = Rxy(theta=-90.0, phi=0.0, qubit=q)
        return self._add_concurrent_ops(sched, ops, last_ref)
    
    def __SetParameters__(self, *args, **kwargs):    
        self.QD_agent = check_acq_channels(self.QD_agent, self.target_q)
        self.__sched_kwargs = dict(current_gate_count=self.current_gate_count)

        # ✅ 依據模式定義 QCoDeS 變數
        if self.run_mode == "training":
            self.acq_labels = ["T0", "T1"]
        else:
            if self.symmetrized_readout:
                self.acq_labels = ["X_reg", "X_inv", "Y_reg", "Y_inv", "Z_reg", "Z_inv"]
            else:
                self.acq_labels = ["X_reg", "Y_reg", "Z_reg"]
            
        self.__acq_param = ManualParameter(name="Acq_Type", unit="", label="Acquisition Type")
        self.__acq_param.batched = True

    def __Compose__(self, *args, **kwargs):
        if self._execution:
            self.__gettable = ScheduleGettable(
                self.QD_agent.quantum_device,
                schedule_function=self.__PulseSchedule__,
                schedule_kwargs=self.__sched_kwargs,
                real_imag=True,
                batched=True,
                num_channels=len(self.target_q)
            )
            self.QD_agent.quantum_device.cfg_sched_repetitions(self.avg_n)
            self.meas_ctrl.gettables(self.__gettable)
            self.meas_ctrl.settables([self.__acq_param])

            acq_indices = np.arange(len(self.acq_labels))
            acq_grid, shot_grid = np.meshgrid(acq_indices, np.arange(self.avg_n), indexing="ij")
            self.meas_ctrl.setpoints_grid((acq_grid.flatten(), shot_grid.flatten()))
        else:
            pass

    def __RunAndGet__(self, *args, **kwargs):
        if self._execution:
            rs_ds = self.meas_ctrl.run(f"Adv_Tomo_{self.run_mode}")
            ds = Dataset()

            shots = self.avg_n
            num_acqs = len(self.acq_labels)

            ds.coords["mixer"] = ["I", "Q"]

            for q_idx, q_name in enumerate(self.target_q):
                y_i, y_q = f"y{q_idx * 2}", f"y{q_idx * 2 + 1}"
                i_data = array(rs_ds[y_i]).reshape(num_acqs, shots)
                q_data = array(rs_ds[y_q]).reshape(num_acqs, shots)

                # ✅ 處理 Training 數據 (使用 train_index 避免與 tomography 的 shots 數衝突)
                if self.run_mode == "training":
                    ds.coords["train_index"] = arange(shots)
                    ds.coords["state"] = ["0", "1"]
                    
                    train_i = array([i_data[0], i_data[1]])
                    train_q = array([q_data[0], q_data[1]])
                    full_train = array([train_i, train_q]) # shape: (mixer, state, train_index)
                    ds[f"{q_name}_training"] = (["mixer", "state", "train_index"], full_train)

                # ✅ 處理 Tomography 數據
                elif self.run_mode == "tomography":
                    ds.coords["index"] = arange(shots)
                    ds.coords["pulse_num"] = [self.current_gate_count]
                    if self.symmetrized_readout: ds.coords["sym"] = ["reg", "inv"]

                    for b_idx, basis in enumerate(["x", "y", "z"]):
                        if self.symmetrized_readout:
                            reg_idx, inv_idx = b_idx * 2, b_idx * 2 + 1
                            basis_i = array([i_data[reg_idx], i_data[inv_idx]])
                            basis_q = array([q_data[reg_idx], q_data[inv_idx]])
                            full_basis = array([basis_i, basis_q]) # shape: (mixer, sym, index)
                            full_basis = np.expand_dims(full_basis, axis=2) # 升維
                            ds[f"{q_name}_{basis}"] = (["mixer", "sym", "pulse_num", "index"], full_basis)
                        else:
                            basis_i, basis_q = i_data[b_idx], q_data[b_idx]
                            full_basis = array([basis_i, basis_q])
                            full_basis = np.expand_dims(full_basis, axis=1)
                            ds[f"{q_name}_{basis}"] = (["mixer", "pulse_num", "index"], full_basis)

            self.dataset = ds
        else:
            pulse_preview(self.QD_agent.quantum_device, self.__PulseSchedule__, self.__sched_kwargs)