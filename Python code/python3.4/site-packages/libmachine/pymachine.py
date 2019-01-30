"""
Python driver for the birdwing machine.  The constructor takes a pointer
to the C object MachineDriver.  These python functions then invoke their
respective functions on the C object.

These functions are broken into two types: action and query commands.

Action commands are treated as generators, and must be iterated over until
they return a kOk error code.  Each of the error codes is also yielded out
of the generator.  Is it up to the caller to analyze these error codes.

Query commands are called and their data is directly returned (so no error
codes).
"""

import ctypes
import datetime
import json
import os

import mbcoreutils.machine_definitions

import kaiten.error

import libmachine.machine_structs

axes_definitions = {
    "x": 0,
    "y": 1,
    "z": 2,
    "a": 3,
    "b": 4,
}

class Machine(object):
    def __init__(self, config, machine_driver_path):
        self._libmachine = self._create_library(machine_driver_path)
        self._machine_driver = self._libmachine.CreateBirdwingMachine()
        self._config = config
        self._libmachine_enabled = True

    ###################
    #Utility Functions#
    ###################

    def _create_library(self, machine_driver_path):
        return ctypes.CDLL(machine_driver_path)

    def close_machine_driver(self):
        """
        Destroys the machine object and closes the shared object library.
        """
        if(self._libmachine_enabled):
            self.destroy_machine(self._machine_driver)
            del self._libmachine

    def create_machine(self):
        """
        Constructs and returns a Machine object for use with this library.
        """
        return self._libmachine.CreateMachine()

    def create_parser_interface(self):
        """
        Constructs and returns a pointer to the type of object that the
        parser expects to be fed for interface with the machine
        """
        return self._libmachine.CreateParserInterface(self._machine_driver)

    def destroy_parser_interface(self, iface):
        """
        Deletes a parser interface previously created with create_parser_interface.

        Please call this, the parser interface is created in libmachine and it is not
        smart enough to kill itself.
        """
        return self._libmachine.DestroyParserInterface(iface)

    def destroy_machine(self, machine):
        """
        Destroys a Machine object.
        """
        self._libmachine.DestroyMachine(machine)
        
    def _convert_axis(self, axis):
        """
        Converts an axis to a usable axis. Takes a char, returns an int

        @param int/str: axis
        @return int: axis
        """
        if axis in axes_definitions.values():
            convert = axis
        elif axis in axes_definitions:
            convert = axes_definitions[axis]
        else:
            raise kaiten.error.InvalidAxisError(axis)
        return convert

    def iterate(self):
        """ iterate the machine.
        @returns The status dict
        """
        status = libmachine.machine_structs.MachineResponseStatus()
        err = self._libmachine.Iterate(ctypes.byref(status), self._machine_driver)
        structure = []
        for k in self._config['toolheads']:
            for l in self._config['toolheads'][k]['locations']:
                if (len(structure)-1) < l:
                    structure.extend(['']*(l-len(structure)+1))
                structure[l] = k
        return status.get_dict(structure)

    def _convert_power_monitor_rail(self, rail):
        return mbcoreutils.machine_definitions.power_monitor_rail[rail]

    def _convert_power_monitor_value(self, value):
        return mbcoreutils.machine_definitions.power_monitor_value[value]

    def _loop(self, callback, *args, timeout=None):
        """
        Call callback(*args) until it does not return not_ready

        If specified, timeout is a maximum integer number of seconds
        to wait for this particular call to finish.
        """
        result = not_ready = kaiten.error.not_ready
        if timeout is not None:
            expiry = (datetime.datetime.now() +
                      datetime.timedelta(seconds=timeout))
        while result == not_ready:
            if self._libmachine_enabled:
                result = callback(*args)
            else:
                result = not_ready
            yield result
            if timeout is not None and datetime.datetime.now() > expiry:
                yield kaiten.error.operation_timed_out
                return  # Just keep going if we ignore timeouts

    @staticmethod
    def unwrap_returns(rets):
        """
        Returns None for an empty tuple or the value for a 1-tuple.
        Because returning those things is dumb.
        @param rets: Tuple to unwrap
        @returns None, value, or tuple for the above cases
        """
        struct_types = (ctypes.Structure,
                        ctypes.LittleEndianStructure,
                        ctypes.BigEndianStructure)
        def maybe_convert(r):
            try:
               return r.get_dict()
            except AttributeError:
                if isinstance(r, ctypes.Array):
                    return list(r)
                else:
                   try:
                       return r.value
                   except AttributeError:
                       # This is probably not a ctypes type so
                       # let the caller figure it out
                       return r
        if len(rets) == 0:
            return None
        if len(rets) == 1:
            return maybe_convert(rets[0])
        else:
            return tuple(map(maybe_convert, rets))

    def has_valid_position_reference(self, axes_bitfield, timeout=None):
        c_axes_bitfield = ctypes.c_uint8(axes_bitfield)
        c_valid = ctypes.c_bool()
        retval = self._libmachine.HasValidPositionReference(c_axes_bitfield, ctypes.byref(c_valid),  self._machine_driver)
        return Machine.unwrap_returns((c_valid,))

    def toolhead_ok(self, index, timeout=None):
        c_index = ctypes.c_uint8(index)
        c_ok = ctypes.c_bool()
        retval = self._libmachine.ToolheadOk(c_index, ctypes.byref(c_ok),  self._machine_driver)
        return Machine.unwrap_returns((c_ok,))

    def immediate_toolhead_error(self, timeout=None):
        c_error = ctypes.c_bool()
        retval = self._libmachine.ImmediateToolheadError(ctypes.byref(c_error),  self._machine_driver)
        return Machine.unwrap_returns((c_error,))

    def clear_position_reference(self, timeout=None):
        retval = self._libmachine.ClearPositionReference( self._machine_driver)

    def set_position_reference(self, axis, timeout=None):
        c_axis = self._convert_axis(axis)
        retval = self._libmachine.SetPositionReference(c_axis,  self._machine_driver)

    def get_tool_uid(self, index, timeout=None):
        c_index = ctypes.c_uint8(index)
        c_uid = ctypes.c_uint32()
        retval = self._libmachine.GetToolUid(c_index, ctypes.byref(c_uid),  self._machine_driver)
        return Machine.unwrap_returns((c_uid,))

    def get_tool_id(self, index, timeout=None):
        c_index = ctypes.c_uint8(index)
        c_id = ctypes.c_uint8()
        retval = self._libmachine.GetToolId(c_index, ctypes.byref(c_id),  self._machine_driver)
        return Machine.unwrap_returns((c_id,))

    def get_tool_usage_stats(self, index, timeout_s, timeout=None):
        c_index = ctypes.c_uint8(index)
        c_timeout_s = ctypes.c_uint8(timeout_s)
        c_usage = libmachine.machine_structs.ToolUsage()
        yield from self._loop(self._libmachine.GetToolUsageStats, c_index, c_timeout_s, ctypes.byref(c_usage), self._machine_driver, timeout=timeout)
        return Machine.unwrap_returns((c_usage,))

    def get_cached_tool_usage_stats(self, index, timeout=None):
        c_index = ctypes.c_uint8(index)
        c_usage = libmachine.machine_structs.ToolUsage()
        retval = self._libmachine.GetCachedToolUsageStats(c_index, ctypes.byref(c_usage),  self._machine_driver)
        return Machine.unwrap_returns((c_usage,))

    def toolhead_blocking(self, index, timeout=None):
        c_index = ctypes.c_uint8(index)
        c_blocking = ctypes.c_bool()
        retval = self._libmachine.ToolheadBlocking(c_index, ctypes.byref(c_blocking),  self._machine_driver)
        return Machine.unwrap_returns((c_blocking,))

    def update_tool_refurb_count(self, index, reset, timeout=None):
        c_index = ctypes.c_uint8(index)
        c_reset = ctypes.c_bool(reset)
        yield from self._loop(self._libmachine.UpdateToolRefurbCount, c_index, c_reset, self._machine_driver, timeout=timeout)

    def reset_tool_usage(self, index, timeout=None):
        c_index = ctypes.c_uint8(index)
        retval = self._libmachine.ResetToolUsage(c_index,  self._machine_driver)

    def update_tool_usage_stats(self, index, timeout=None):
        c_index = ctypes.c_uint8(index)
        yield from self._loop(self._libmachine.UpdateToolUsageStats, c_index, self._machine_driver, timeout=timeout)

    def scan_toolheads(self, timeout=None):
        yield from self._loop(self._libmachine.ScanToolheads, self._machine_driver, timeout=timeout)

    def connect_tool(self, index, abort_toolhead_only, timeout=None):
        c_index = ctypes.c_uint8(index)
        c_abort_toolhead_only = ctypes.c_bool(abort_toolhead_only)
        yield from self._loop(self._libmachine.ConnectTool, c_index, c_abort_toolhead_only, self._machine_driver, timeout=timeout)

    def is_tool_connected(self, index, timeout=None):
        c_index = ctypes.c_uint8(index)
        c_connected = ctypes.c_bool()
        retval = self._libmachine.IsToolConnected(c_index, ctypes.byref(c_connected),  self._machine_driver)
        return Machine.unwrap_returns((c_connected,))

    def set_z_pause_mm(self, z_pause_mm, timeout=None):
        c_z_pause_mm = ctypes.c_float(z_pause_mm)
        yield from self._loop(self._libmachine.SetZPauseMm, c_z_pause_mm, self._machine_driver, timeout=timeout)

    def clear_z_pause_mm(self, mm, timeout=None):
        c_mm = ctypes.c_float(mm)
        yield from self._loop(self._libmachine.ClearZPauseMm, c_mm, self._machine_driver, timeout=timeout)

    def clear_all_z_pause(self, timeout=None):
        yield from self._loop(self._libmachine.ClearAllZPause, self._machine_driver, timeout=timeout)

    def reset_z_pause_index(self, timeout=None):
        yield from self._loop(self._libmachine.ResetZPauseIndex, self._machine_driver, timeout=timeout)

    def enable_z_pause(self, timeout=None):
        yield from self._loop(self._libmachine.EnableZPause, self._machine_driver, timeout=timeout)

    def disable_z_pause(self, timeout=None):
        yield from self._loop(self._libmachine.DisableZPause, self._machine_driver, timeout=timeout)

    def set_toolhead_idle_update_period(self, index, time, timeout=None):
        c_index = ctypes.c_uint8(index)
        c_time = ctypes.c_float(time)
        retval = self._libmachine.SetToolheadIdleUpdatePeriod(c_index, c_time,  self._machine_driver)

    def toggle_filament_jam(self, on, timeout=None):
        c_on = ctypes.c_bool(on)
        yield from self._loop(self._libmachine.ToggleFilamentJam, c_on, self._machine_driver, timeout=timeout)

    def motor_enable(self, axis, enable, timeout=None):
        c_axis = self._convert_axis(axis)
        c_enable = ctypes.c_bool(enable)
        yield from self._loop(self._libmachine.MotorEnable, c_axis, c_enable, self._machine_driver, timeout=timeout)

    def home_axis(self, axis, speed, flip_direction=False, set_position=True, blocking_home=False, timeout=None):
        c_axis = self._convert_axis(axis)
        c_speed = ctypes.c_float(speed)
        c_flip_direction = ctypes.c_bool(flip_direction)
        c_set_position = ctypes.c_bool(set_position)
        c_blocking_home = ctypes.c_bool(blocking_home)
        yield from self._loop(self._libmachine.HomeAxis, c_axis, c_speed, c_flip_direction, c_set_position, c_blocking_home, self._machine_driver, timeout=timeout)

    def endstop_triggered(self, axis, timeout=None):
        c_axis = self._convert_axis(axis)
        c_triggered = ctypes.c_bool()
        retval = self._libmachine.EndstopTriggered(c_axis, ctypes.byref(c_triggered),  self._machine_driver)
        return Machine.unwrap_returns((c_triggered,))

    def move(self, point_mm, mm_per_second, relative, timeout=None):
        c_point_mm = (ctypes.c_float*mbcoreutils.machine_definitions.constants['axis_count'])(*point_mm)
        c_mm_per_second = ctypes.c_float(mm_per_second)
        c_relative = (ctypes.c_bool*mbcoreutils.machine_definitions.constants['axis_count'])(*relative)
        yield from self._loop(self._libmachine.Move, c_point_mm, c_mm_per_second, c_relative, self._machine_driver, timeout=timeout)

    def toolhead_acknowledged_hes(self, index, timeout=None):
        c_index = ctypes.c_uint8(index)
        c_acknowledged = ctypes.c_bool()
        retval = self._libmachine.ToolheadAcknowledgedHes(c_index, ctypes.byref(c_acknowledged),  self._machine_driver)
        return Machine.unwrap_returns((c_acknowledged,))

    def begin_hes_log(self, index, size, immediate, timeout=None):
        c_index = ctypes.c_uint8(index)
        c_size = ctypes.c_uint16(size)
        c_immediate = ctypes.c_bool(immediate)
        yield from self._loop(self._libmachine.BeginHesLog, c_index, c_size, c_immediate, self._machine_driver, timeout=timeout)

    def end_hes_log(self, index, timeout=None):
        c_index = ctypes.c_uint8(index)
        yield from self._loop(self._libmachine.EndHesLog, c_index, self._machine_driver, timeout=timeout)

    def get_hes_log(self, index, size, timeout=None):
        c_index = ctypes.c_uint8(index)
        c_size = ctypes.c_uint16(size)
        c_log = (ctypes.c_int32*size)()
        retval = self._libmachine.GetHesLog(c_index, c_size, ctypes.byref(c_log),  self._machine_driver)
        return Machine.unwrap_returns((c_log,))

    def hes_log_loaded(self, index, timeout=None):
        c_index = ctypes.c_uint8(index)
        c_loaded = ctypes.c_bool()
        retval = self._libmachine.HesLogLoaded(c_index, ctypes.byref(c_loaded),  self._machine_driver)
        return Machine.unwrap_returns((c_loaded,))

    def get_raw_hes_value(self, index, timeout=None):
        c_index = ctypes.c_uint8(index)
        c_saturated = ctypes.c_bool()
        c_value = ctypes.c_int16()
        yield from self._loop(self._libmachine.GetRawHesValue, c_index, ctypes.byref(c_saturated), ctypes.byref(c_value), self._machine_driver, timeout=timeout)
        return Machine.unwrap_returns((c_saturated,c_value,))

    def move_axis(self, axis, point_mm, mm_per_second, relative, timeout=None):
        c_axis = self._convert_axis(axis)
        c_point_mm = ctypes.c_float(point_mm)
        c_mm_per_second = ctypes.c_float(mm_per_second)
        c_relative = ctypes.c_bool(relative)
        yield from self._loop(self._libmachine.MoveAxis, c_axis, c_point_mm, c_mm_per_second, c_relative, self._machine_driver, timeout=timeout)

    def perform_toolhead_self_check(self, index, timeout=None):
        c_index = ctypes.c_uint8(index)
        yield from self._loop(self._libmachine.PerformToolheadSelfCheck, c_index, self._machine_driver, timeout=timeout)

    def get_toolhead_self_check_results(self, index, filepath, timeout=None):
        c_index = ctypes.c_uint8(index)
        c_filepath = ctypes.c_char_p(filepath)
        c_succeeded = ctypes.c_bool()
        retval = self._libmachine.GetToolheadSelfCheckResults(c_index, c_filepath, ctypes.byref(c_succeeded),  self._machine_driver)
        return Machine.unwrap_returns((c_succeeded,))

    def get_extended_toolhead_self_check_results(self, index, timeout=None):
        c_index = ctypes.c_uint8(index)
        c_out_buffer = (ctypes.c_char*256)()
        c_out_size = ctypes.c_uint16()
        retval = self._libmachine.GetExtendedToolheadSelfCheckResults(c_index, ctypes.byref(c_out_buffer), ctypes.byref(c_out_size),  self._machine_driver)
        return Machine.unwrap_returns((c_out_buffer,c_out_size,))

    def set_moose_chamber_brightness(self, brightness, timeout=None):
        c_brightness = ctypes.c_float(brightness)
        retval = self._libmachine.SetMooseChamberBrightness(c_brightness,  self._machine_driver)

    def led_sleep(self, timeout=None):
        yield from self._loop(self._libmachine.LedSleep, self._machine_driver, timeout=timeout)

    def led_wake(self, timeout=None):
        yield from self._loop(self._libmachine.LedWake, self._machine_driver, timeout=timeout)

    def quick_pause(self, state, timeout=None):
        c_state = ctypes.c_bool(state)
        yield from self._loop(self._libmachine.QuickPause, c_state, self._machine_driver, timeout=timeout)

    def toggle_acceleration(self, state, timeout=None):
        c_state = ctypes.c_bool(state)
        yield from self._loop(self._libmachine.ToggleAcceleration, c_state, self._machine_driver, timeout=timeout)

    def toggle_acceleration_lookahead(self, state, timeout=None):
        c_state = ctypes.c_bool(state)
        yield from self._loop(self._libmachine.ToggleAccelerationLookahead, c_state, self._machine_driver, timeout=timeout)

    def toggle_expend_buffer(self, state, timeout=None):
        c_state = ctypes.c_bool(state)
        yield from self._loop(self._libmachine.ToggleExpendBuffer, c_state, self._machine_driver, timeout=timeout)

    def set_extruder_delay(self, delay, timeout=None):
        c_delay = int(delay)
        yield from self._loop(self._libmachine.SetExtruderDelay, c_delay, self._machine_driver, timeout=timeout)

    def toggle_toolhead_syncing(self, state, timeout=None):
        c_state = ctypes.c_bool(state)
        yield from self._loop(self._libmachine.ToggleToolheadSyncing, c_state, self._machine_driver, timeout=timeout)

    def enable_toolhead_idle(self, timeout=None):
        yield from self._loop(self._libmachine.EnableToolheadIdle, self._machine_driver, timeout=timeout)

    def set_temperature_target(self, index, temperature, timeout=None):
        c_index = ctypes.c_uint8(index)
        c_temperature = ctypes.c_int16(temperature)
        yield from self._loop(self._libmachine.SetTemperatureTarget, c_index, c_temperature, self._machine_driver, timeout=timeout)

    def toggle_fan(self, index, state, timeout=None):
        c_index = ctypes.c_uint8(index)
        c_state = ctypes.c_bool(state)
        yield from self._loop(self._libmachine.ToggleFan, c_index, c_state, self._machine_driver, timeout=timeout)

    def set_fan_duty(self, index, duty, timeout=None):
        c_index = ctypes.c_uint8(index)
        c_duty = ctypes.c_float(duty)
        yield from self._loop(self._libmachine.SetFanDuty, c_index, c_duty, self._machine_driver, timeout=timeout)

    def set_heater_duty(self, index, duty, timeout=None):
        c_index = ctypes.c_uint8(index)
        c_duty = ctypes.c_float(duty)
        yield from self._loop(self._libmachine.SetHeaterDuty, c_index, c_duty, self._machine_driver, timeout=timeout)

    def cool(self, timeout=None):
        yield from self._loop(self._libmachine.Cool, self._machine_driver, timeout=timeout)

    def move_buffer_empty(self, ignore_toolhead=False, timeout=None):
        c_ignore_toolhead = ctypes.c_bool(ignore_toolhead)
        c_empty = ctypes.c_bool()
        retval = self._libmachine.MoveBufferEmpty(c_ignore_toolhead, ctypes.byref(c_empty),  self._machine_driver)
        return Machine.unwrap_returns((c_empty,))

    def acceleration_buffer_empty(self, timeout=None):
        c_empty = ctypes.c_bool()
        retval = self._libmachine.AccelerationBufferEmpty(ctypes.byref(c_empty),  self._machine_driver)
        return Machine.unwrap_returns((c_empty,))

    def log_tool_eeprom(self, index, timeout=None):
        c_index = ctypes.c_uint8(index)
        yield from self._loop(self._libmachine.LogToolEeprom, c_index, self._machine_driver, timeout=timeout)

    def wait_for_heaters_at_target(self, timeout_minutes, check, timeout=None):
        c_timeout_minutes = ctypes.c_uint8(timeout_minutes)
        c_check = (ctypes.c_bool*self._config['toolhead_count'])(*check)
        yield from self._loop(self._libmachine.WaitForHeatersAtTarget, c_timeout_minutes, c_check, self._machine_driver, timeout=timeout)

    def wait_for_heaters_at_least_target(self, timeout_minutes, check, timeout=None):
        c_timeout_minutes = ctypes.c_uint8(timeout_minutes)
        c_check = (ctypes.c_bool*self._config['toolhead_count'])(*check)
        yield from self._loop(self._libmachine.WaitForHeatersAtLeastTarget, c_timeout_minutes, c_check, self._machine_driver, timeout=timeout)

    def any_heater_above_temp(self, temperature_c, timeout=None):
        c_temperature_c = ctypes.c_uint16(temperature_c)
        c_above = ctypes.c_bool()
        retval = self._libmachine.AnyHeaterAboveTemp(c_temperature_c, ctypes.byref(c_above),  self._machine_driver)
        return Machine.unwrap_returns((c_above,))

    def set_led_brightness(self, index, brightness, timeout=None):
        c_index = ctypes.c_uint8(index)
        c_brightness = ctypes.c_float(brightness)
        yield from self._loop(self._libmachine.SetLedBrightness, c_index, c_brightness, self._machine_driver, timeout=timeout)

    def set_led_blink(self, index, brightness, period, timeout=None):
        c_index = ctypes.c_uint8(index)
        c_brightness = ctypes.c_uint8(brightness)
        c_period = ctypes.c_float(period)
        yield from self._loop(self._libmachine.SetLedBlink, c_index, c_brightness, c_period, self._machine_driver, timeout=timeout)

    def set_interface_address(self, address, timeout=None):
        c_address = ctypes.c_uint8(address)
        retval = self._libmachine.SetInterfaceAddress(c_address,  self._machine_driver)

    def set_knob_color(self, red, green, blue, brightness, timeout=None):
        c_red = ctypes.c_float(red)
        c_green = ctypes.c_float(green)
        c_blue = ctypes.c_float(blue)
        c_brightness = ctypes.c_float(brightness)
        retval = self._libmachine.SetKnobColor(c_red, c_green, c_blue, c_brightness,  self._machine_driver)

    def set_chamber_color(self, red, green, blue, brightness, timeout=None):
        c_red = ctypes.c_float(red)
        c_green = ctypes.c_float(green)
        c_blue = ctypes.c_float(blue)
        c_brightness = ctypes.c_float(brightness)
        retval = self._libmachine.SetChamberColor(c_red, c_green, c_blue, c_brightness,  self._machine_driver)

    def set_knob_blink(self, period, timeout=None):
        c_period = ctypes.c_float(period)
        retval = self._libmachine.SetKnobBlink(c_period,  self._machine_driver)

    def set_chamber_blink(self, period, timeout=None):
        c_period = ctypes.c_float(period)
        retval = self._libmachine.SetChamberBlink(c_period,  self._machine_driver)

    def set_position(self, axis, position_mm, timeout=None):
        c_axis = self._convert_axis(axis)
        c_position_mm = ctypes.c_float(position_mm)
        yield from self._loop(self._libmachine.SetPosition, c_axis, c_position_mm, self._machine_driver, timeout=timeout)

    def is_initialized(self, timeout=None):
        c_initialized = ctypes.c_bool()
        retval = self._libmachine.IsInitialized(ctypes.byref(c_initialized),  self._machine_driver)
        return Machine.unwrap_returns((c_initialized,))

    def abort(self, timeout=5):
        yield from self._loop(self._libmachine.Abort, self._machine_driver, timeout=timeout)

    def fast_abort(self, timeout=5):
        retval = self._libmachine.FastAbort( self._machine_driver)

    def motor_abort(self, shutdown=False, timeout=None):
        c_shutdown = ctypes.c_bool(shutdown)
        yield from self._loop(self._libmachine.MotorAbort, c_shutdown, self._machine_driver, timeout=timeout)

    def close_and_cleanup(self, timeout=None):
        retval = self._libmachine.CloseAndCleanup( self._machine_driver)

    def disable_spi(self, timeout=None):
        retval = self._libmachine.DisableSpi( self._machine_driver)

    def enable_spi(self, timeout=None):
        retval = self._libmachine.EnableSpi( self._machine_driver)

    def shutdown(self, timeout=120):
        yield from self._loop(self._libmachine.Shutdown, self._machine_driver, timeout=timeout)

    def get_temperature(self, index, timeout=None):
        c_index = ctypes.c_uint8(index)
        c_temperature = ctypes.c_int16()
        retval = self._libmachine.GetTemperature(c_index, ctypes.byref(c_temperature),  self._machine_driver)
        return Machine.unwrap_returns((c_temperature,))

    def load_temperature_settings(self, active_temperatures, timeout=None):
        c_active_temperatures = (ctypes.c_int16*self._config['toolhead_count'])(*active_temperatures)
        yield from self._loop(self._libmachine.LoadTemperatureSettings, c_active_temperatures, self._machine_driver, timeout=timeout)

    def get_temperature_settings(self, timeout=None):
        c_active_temperatures = (ctypes.c_int16*self._config['toolhead_count'])()
        retval = self._libmachine.GetTemperatureSettings(c_active_temperatures,  self._machine_driver)
        return Machine.unwrap_returns((list(c_active_temperatures),))

    def set_move_buffer_position(self, axes_position, timeout=None):
        c_axes_position = (ctypes.c_float*mbcoreutils.machine_definitions.constants['axis_count'])(*axes_position)
        yield from self._loop(self._libmachine.SetMoveBufferPosition, c_axes_position, self._machine_driver, timeout=timeout)

    def get_move_buffer_position(self, timeout=None):
        c_axes_position = (ctypes.c_float*mbcoreutils.machine_definitions.constants['axis_count'])()
        retval = self._libmachine.GetMoveBufferPosition(c_axes_position,  self._machine_driver)
        return Machine.unwrap_returns((list(c_axes_position),))

    def get_axes_position(self, timeout=None):
        c_axes_position = (ctypes.c_float*mbcoreutils.machine_definitions.constants['axis_count'])()
        yield from self._loop(self._libmachine.GetAxesPosition, c_axes_position, self._machine_driver, timeout=timeout)
        return Machine.unwrap_returns((list(c_axes_position),))

    def heat(self, timeout=None):
        yield from self._loop(self._libmachine.Heat, self._machine_driver, timeout=timeout)

    def power_monitor_close(self, timeout=None):
        yield from self._loop(self._libmachine.PowerMonitorClose, self._machine_driver, timeout=timeout)

    def power_monitor_init(self, timeout=None):
        yield from self._loop(self._libmachine.PowerMonitorInit, self._machine_driver, timeout=timeout)

    def query_power_info(self, timeout=None):
        yield from self._loop(self._libmachine.QueryPowerInfo, self._machine_driver, timeout=timeout)

    def reset_heater_watchdog(self, timeout=None):
        retval = self._libmachine.ResetHeaterWatchdog( self._machine_driver)

    def get_filament_presence(self, index, timeout=None):
        c_index = ctypes.c_uint8(index)
        c_present = ctypes.c_bool()
        retval = self._libmachine.GetFilamentPresence(c_index, ctypes.byref(c_present),  self._machine_driver)
        return Machine.unwrap_returns((c_present,))

    def load_filament_jam_settings(self, index, steps_per_mm, timeout=None):
        c_index = ctypes.c_uint8(index)
        c_steps_per_mm = ctypes.c_float(steps_per_mm)
        yield from self._loop(self._libmachine.LoadFilamentJamSettings, c_index, c_steps_per_mm, self._machine_driver, timeout=timeout)

    def get_toolhead_firmware_version(self, index, timeout=None):
        c_index = ctypes.c_uint8(index)
        c_major = ctypes.c_uint8()
        c_minor = ctypes.c_uint8()
        c_build = ctypes.c_uint16()
        retval = self._libmachine.GetToolheadFirmwareVersion(c_index, ctypes.byref(c_major), ctypes.byref(c_minor), ctypes.byref(c_build),  self._machine_driver)
        return Machine.unwrap_returns((c_major,c_minor,c_build,))

    def program_toolhead(self, filepath, index, timeout=None):
        c_filepath = ctypes.c_char_p(filepath)
        c_index = ctypes.c_uint8(index)
        yield from self._loop(self._libmachine.ProgramToolhead, c_filepath, c_index, self._machine_driver, timeout=timeout)

    def program_yonkers(self, filepath, index, timeout=None):
        c_filepath = ctypes.c_char_p(filepath)
        c_index = ctypes.c_uint8(index)
        yield from self._loop(self._libmachine.ProgramYonkers, c_filepath, c_index, self._machine_driver, timeout=timeout)

    def load_print_meta_settings(self, meta_file_string, timeout=None):
        c_meta_file_string = ctypes.c_char_p(meta_file_string)
        retval = self._libmachine.LoadPrintMetaSettings(c_meta_file_string,  self._machine_driver)

    def initialize_from_settings(self, meta_file_string, timeout=None):
        c_meta_file_string = ctypes.c_char_p(meta_file_string)
        yield from self._loop(self._libmachine.InitializeFromSettings, c_meta_file_string, self._machine_driver, timeout=timeout)

    def toggle_toolhead_power(self, index, power_state, timeout=None):
        c_index = ctypes.c_uint8(index)
        c_power_state = ctypes.c_bool(power_state)
        retval = self._libmachine.ToggleToolheadPower(c_index, c_power_state,  self._machine_driver)

    def change_tool(self, index, timeout=None):
        c_index = ctypes.c_uint8(index)
        yield from self._loop(self._libmachine.ChangeTool, c_index, self._machine_driver, timeout=timeout)

    def get_extrusion_distance_percent(self, timeout=None):
        c_percent = ctypes.c_float()
        retval = self._libmachine.GetExtrusionDistancePercent(ctypes.byref(c_percent),  self._machine_driver)
        return Machine.unwrap_returns((c_percent,))

    def toggle_extrusion_percent_update(self, state, timeout=None):
        c_state = ctypes.c_bool(state)
        retval = self._libmachine.ToggleExtrusionPercentUpdate(c_state,  self._machine_driver)

    def reset_extrusion_distance(self, timeout=None):
        retval = self._libmachine.ResetExtrusionDistance( self._machine_driver)

    def get_heater_progress_percent(self, timeout=None):
        c_percent = ctypes.c_float()
        retval = self._libmachine.GetHeaterProgressPercent(ctypes.byref(c_percent),  self._machine_driver)
        return Machine.unwrap_returns((c_percent,))

    def configure_hes(self, index, exponent, threshold, timeout=None):
        c_index = ctypes.c_uint8(index)
        c_exponent = ctypes.c_uint8(exponent)
        c_threshold = ctypes.c_uint16(threshold)
        yield from self._loop(self._libmachine.ConfigureHes, c_index, c_exponent, c_threshold, self._machine_driver, timeout=timeout)

    def change_hes_sample_rate(self, index, rate, timeout=None):
        c_index = ctypes.c_uint8(index)
        c_rate = ctypes.c_float(rate)
        c_actual_rate = ctypes.c_float()
        yield from self._loop(self._libmachine.ChangeHesSampleRate, c_index, c_rate, ctypes.byref(c_actual_rate), self._machine_driver, timeout=timeout)
        return Machine.unwrap_returns((c_actual_rate,))

    def sample_power(self, rail, value, samples, timeout=None):
        c_rail = self._convert_power_monitor_rail(rail)
        c_value = self._convert_power_monitor_value(value)
        c_samples = ctypes.c_uint16(samples)
        yield from self._loop(self._libmachine.SamplePower, c_rail, c_value, c_samples, self._machine_driver, timeout=timeout)

    def get_power_value(self, rail, value, timeout=None):
        c_rail = self._convert_power_monitor_rail(rail)
        c_value = self._convert_power_monitor_value(value)
        c_single = ctypes.c_uint16()
        c_average = ctypes.c_float()
        c_stddev = ctypes.c_float()
        retval = self._libmachine.GetPowerValue(c_rail, c_value, ctypes.byref(c_single), ctypes.byref(c_average), ctypes.byref(c_stddev),  self._machine_driver)
        return Machine.unwrap_returns((c_single,c_average,c_stddev,))

    def find_knob_z(self, limit, speed, timeout=None):
        c_limit = ctypes.c_float(limit)
        c_speed = ctypes.c_float(speed)
        yield from self._loop(self._libmachine.FindKnobZ, c_limit, c_speed, self._machine_driver, timeout=timeout)

    def clear_all_buffers(self, timeout=None):
        yield from self._loop(self._libmachine.ClearAllBuffers, self._machine_driver, timeout=timeout)

    def pru_is_paused(self, timeout=None):
        c_running = ctypes.c_bool()
        retval = self._libmachine.PruIsPaused(ctypes.byref(c_running),  self._machine_driver)
        return Machine.unwrap_returns((c_running,))

    def get_current_command_index(self, timeout=None):
        c_index = ctypes.c_int32()
        retval = self._libmachine.GetCurrentCommandIndex(ctypes.byref(c_index),  self._machine_driver)
        return Machine.unwrap_returns((c_index,))

    def sync_state_confirmed(self, index, timeout=None):
        c_index = ctypes.c_uint8(index)
        c_confirmed = ctypes.c_bool()
        retval = self._libmachine.SyncStateConfirmed(c_index, ctypes.byref(c_confirmed),  self._machine_driver)
        return Machine.unwrap_returns((c_confirmed,))

    def get_sync_state(self, index, timeout=None):
        c_index = ctypes.c_uint8(index)
        c_state = ctypes.c_bool()
        retval = self._libmachine.GetSyncState(c_index, ctypes.byref(c_state),  self._machine_driver)
        return Machine.unwrap_returns((c_state,))

    def set_print_context(self, state, filename, timeout=None):
        c_state = ctypes.c_bool(state)
        c_filename = ctypes.c_char_p(filename)
        retval = self._libmachine.SetPrintContext(c_state, c_filename,  self._machine_driver)
