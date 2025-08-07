from qblox_drive_AS.support.Pulser import ScheduleConductor
from qblox_drive_AS.support.Pulse_schedule_library import Schedule, X, Reset, Rxy, Measure, BinMode
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
        self._gate_counts:list = arange(1, 100)  # 1~99 X gates
        self._avg_n:int = 100

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
                    if self._init_state == "plus":
                        last_op = sched.add(Rxy(theta=90.0, phi=0, qubit=q), ref_op=reset)  # H gate ≈ Rx(pi/2)
                    elif self._init_state == "plus_i":
                        last_op = sched.add(Rxy(theta=90.0, phi=90.0, qubit=q), ref_op=reset)
                    else:
                        last_op = reset
                    # X gates3
                    for _ in range(x_gate_count):
                        last_op = sched.add(X(q))

                # Tomography: X, Y, Z bases
                    if basis == 'X':
                        sched.add(Rxy(theta=90.0, phi=90.0, qubit=q))
                    elif basis == 'Y':
                        sched.add(Rxy(theta=90.0, phi=0, qubit=q))

                    # 加 buffer
                    sched.add(Measure(q,
                                    acq_index=acq_idx * 3 + ['X', 'Y', 'Z'].index(basis),
                                    acq_protocol="SSBIntegrationComplex",
                                    bin_mode=BinMode.APPEND))

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
                gate_grid.flatten(),
                basis_grid.flatten(),
                shot_grid.flatten(),
            ))


        else:
            self.__sched_kwargs['gate_counts'] = [1, 2, 3]  # preview 3 points only

    def __RunAndGet__(self, *args, **kwargs):
        if self._execution:
            rs_ds = self.meas_ctrl.run("X tomography")
            ds = Dataset()

            # ✅ 確保 target_q 是 string
            target_q = self._target_q[0] if isinstance(self._target_q, list) else self._target_q

            gate_len = len(self._gate_counts)
            shots = self._avg_n
            i_data = array(rs_ds["y0"]).reshape(gate_len, 3, shots)  # shape: (gate, basis, shots)
            q_data = array(rs_ds["y1"]).reshape(gate_len, 3, shots)

            # ✅ 設定座標
            ds.coords["mixer"] = ["I", "Q"]
            ds.coords["pulse_num"] = self._gate_counts
            ds.coords["index"] = arange(i_data.shape[-1])

            # ✅ 建立 q0_x, q0_y, q0_z
            basis_labels = ["x", "y", "z"]
            for basis_idx, basis in enumerate(basis_labels):
                # shape: (mixer, pulse_num, index)
                i_part = i_data[:, basis_idx, :].T  # → shape: (index, pulse_num)
                q_part = q_data[:, basis_idx, :].T
                full_data = array([i_part, q_part])  # → shape: (mixer, index, pulse_num)
                full_data = full_data.transpose(0, 2, 1)  # → (mixer, pulse_num, index)

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
