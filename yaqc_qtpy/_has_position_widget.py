from collections import deque
import time
import warnings
from functools import partial

from qtpy import QtWidgets, QtCore
import qtypes
import yaqc
import numpy as np
import yaq_traits

from ._plot import Plot1D, BigNumberWidget
from . import qtype_items


class HasPositionWidget(QtWidgets.QSplitter):
    def __init__(self, qclient, *, parent=None):
        super().__init__(parent=parent)
        self.qclient = qclient
        self._create_main_frame()
        # plotting variables
        self._position_buffer = deque(maxlen=250)
        self._timestamp_buffer = deque(maxlen=250)
        # signals and slots
        if "position" in self.qclient.properties:
            self.qclient.properties.position.updated.connect(self._on_position_updated)
            self.qclient.properties.destination.updated.connect(self._on_destination_updated)
        if "has-limits" in self.qclient.traits:
            self.qclient.get_limits.finished.connect(self._on_get_limits)
            self.qclient.get_limits()

    def _create_main_frame(self):
        # plot
        plot_container_widget = QtWidgets.QWidget()
        plot_container_widget.setLayout(QtWidgets.QVBoxLayout())
        plot_container_widget.layout().setContentsMargins(0, 0, 0, 0)
        self._big_number = BigNumberWidget()
        plot_container_widget.layout().addWidget(self._big_number)
        self.plot_widget = Plot1D()
        self._minimum_line = self.plot_widget.add_infinite_line(
            hide=False, angle=0, color="#cc6666"
        )
        self._maximum_line = self.plot_widget.add_infinite_line(
            hide=False, angle=0, color="#cc6666"
        )
        self._destination_line = self.plot_widget.add_infinite_line(
            hide=False, angle=0, color="#b5bd68"
        )
        self._scatter = self.plot_widget.add_scatter()
        plot_container_widget.layout().addWidget(self.plot_widget)
        self.addWidget(plot_container_widget)

        # right hand tree
        self._root_item = qtypes.Null()

        # plot control
        plot_item = qtypes.Null("plot")
        self._root_item.append(plot_item)
        x_item = qtypes.Null("x axis")
        plot_item.append(x_item)
        self._cached_count = qtypes.Integer("cached values", value=250, minimum=0, maximum=1000)
        self._cached_count.updated_connect(self._on_cached_count_updated)
        x_item.append(self._cached_count)
        self._xmin = qtypes.Float("xmin (s)", value=-60, minimum=-100, maximum=0)
        self._xmin.updated_connect(self._on_xmin_updated)
        x_item.append(self._xmin)
        y_item = qtypes.Null("y axis")
        plot_item.append(y_item)
        self._lock_ylim = qtypes.Bool("lock ylim", value=False)
        self._lock_ylim.updated_connect(self._on_lock_ylim)
        y_item.append(self._lock_ylim)
        self._ymax = qtypes.Float("ymax", disabled=True)
        y_item.append(self._ymax)
        self._ymin = qtypes.Float("ymin", disabled=True)
        y_item.append(self._ymin)
        self._reset_ylim = qtypes.Button("reset ylim", text="reset")
        self._reset_ylim.updated_connect(self._on_reset_ylim)
        y_item.append(self._reset_ylim)

        # id
        id_item = qtypes.Null("id")
        self._root_item.append(id_item)
        for key, value in self.qclient.id().items():
            id_item.append(qtypes.String(label=key, disabled=True, value=value))
            if key == "name":
                self._big_number.set_label(value)

        # traits
        traits_item = qtypes.Null("traits")
        self._root_item.append(traits_item)
        for trait in yaq_traits.__traits__.traits.keys():
            traits_item.append(
                qtypes.Bool(label=trait, disabled=True, value=trait in self.qclient.traits)
            )

        # properties
        properties_item = qtypes.Null("properties")
        self._root_item.append(properties_item)
        qtype_items.append_properties(self.qclient, properties_item)

        # is-homeable
        if "is-homeable" in self.qclient.traits:

            def on_clicked(_, qclient):
                qclient.home()

            home_button = qtypes.Button("is-homeable", text="home")
            self._root_item.append(home_button)
            home_button.updated_connect(partial(on_clicked, qclient=self.qclient))

        self._tree_widget = qtypes.TreeWidget(self._root_item)
        self.addWidget(self._tree_widget)
        self._tree_widget["plot"].expand()
        self._tree_widget["id"].expand(0)
        self._tree_widget["properties"].expand(0)
        self._tree_widget.resizeColumnToContents(0)

    def _on_cached_count_updated(self, value):
        position_buffer = deque(maxlen=value["value"])
        timestamp_buffer = deque(maxlen=value["value"])

        for p, t in zip(self._position_buffer, self._timestamp_buffer):
            position_buffer.append(p)
            timestamp_buffer.append(t)

        self._position_buffer = position_buffer
        self._timestamp_buffer = timestamp_buffer

    def _on_destination_updated(self, destination):
        self._destination_line.setValue(destination)

    def _on_get_limits(self, result):
        self._minimum_line.setValue(np.nanmin(result))
        self._maximum_line.setValue(np.nanmax(result))

    def _on_lock_ylim(self, dic):
        locked = dic["value"]
        self._ymin.set({"disabled": not locked})
        self._ymax.set({"disabled": not locked})

    def _on_position_updated(self, position):
        self._big_number.set_number(position)
        # roll over, enter new data
        self._position_buffer.append(position)
        self._timestamp_buffer.append(time.time())
        # x axis
        with warnings.catch_warnings():
            try:
                self.plot_widget.set_xlim(self._xmin.get_value(), 0)
            except:
                pass
        # y axis
        if not self._lock_ylim.get_value():
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                ymin = self._ymin.get_value()
                ymax = self._ymax.get_value()
                ymin = np.nanmin([np.nanmin(self._position_buffer), ymin])
                ymax = np.nanmax([np.nanmax(self._position_buffer), ymax])
            if ymin == ymax:
                ymin -= 1e-6
                ymax += 1e-6
            self._ymin.set_value(ymin)
            self._ymax.set_value(ymax)
        if np.isnan(self._ymin.get_value()):
            self.plot_widget.set_ylim(-1, 1)
            return
        if np.isnan(self._ymax.get_value()):
            self.plot_widget.set_ylim(-1, 1)
            return
        self.plot_widget.set_ylim(self._ymin.get_value(), self._ymax.get_value())
        # set data
        self._scatter.setData(
            np.array(self._timestamp_buffer) - time.time(), self._position_buffer
        )
        # labels
        self.plot_widget.set_labels(xlabel="seconds", ylabel="position")

    def _on_reset_ylim(self, _=None):
        self._ymin.set_value(np.nanmin(self._position_buffer))
        self._ymax.set_value(np.nanmax(self._position_buffer))

    def _on_xmin_updated(self, value):
        self.plot_widget.set_xlim(value["value"], 0)

    def close(self):
        super().close()
        if "position" in self.qclient.properties:
            self.qclient.properties.position.updated.disconnect(self._on_position_updated)
            self.qclient.properties.destination.updated.disconnect(self._on_destination_updated)
        if "has-limits" in self.qclient.traits:
            self.qclient.get_limits.finished.disconnect(self._on_get_limits)
