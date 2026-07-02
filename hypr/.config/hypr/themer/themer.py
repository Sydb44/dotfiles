#!/usr/bin/env python3
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, Gdk, GLib
import subprocess
import re
import os

CONF_PATH = os.path.expanduser("~/.config/hypr/hyprland.conf")


def hyprctl(keyword, value):
    subprocess.run(["hyprctl", "keyword", keyword, value], capture_output=True)


def rgba_to_gdk(rgba_str):
    m = re.match(r'rgba\(([0-9a-fA-F]{2})([0-9a-fA-F]{2})([0-9a-fA-F]{2})([0-9a-fA-F]{2})\)', rgba_str)
    if m:
        r, g, b, a = [int(x, 16) / 255.0 for x in m.groups()]
        color = Gdk.RGBA()
        color.red, color.green, color.blue, color.alpha = r, g, b, a
        return color
    color = Gdk.RGBA()
    color.red, color.green, color.blue, color.alpha = 0.4, 0.7, 0.4, 1.0
    return color


def gdk_to_rgba(color):
    r = int(color.red * 255)
    g = int(color.green * 255)
    b = int(color.blue * 255)
    a = int(color.alpha * 255)
    return f"rgba({r:02x}{g:02x}{b:02x}{a:02x})"


CSS = """
window {
    background-color: #0a130b;
}
.section-label {
    color: #4aaa60;
    font-weight: bold;
    font-size: 10px;
    letter-spacing: 1px;
    margin-top: 6px;
}
label {
    color: #a8c8aa;
    font-size: 11px;
}
.value-label {
    color: #5acc72;
    font-size: 10px;
    min-width: 32px;
}
scale trough {
    background-color: #162018;
    border-radius: 4px;
    min-height: 4px;
}
scale highlight {
    background-color: #38aa55;
    border-radius: 4px;
}
scale slider {
    background-color: #00ddc8;
    border-radius: 50%;
    min-width: 0;
    min-height: 0;
    -gtk-icon-size: 12px;
    border: none;
    box-shadow: none;
}
notebook {
    background-color: #0a130b;
}
notebook > header {
    background-color: #0d1a0f;
    border-bottom: 1px solid #1a3a1e;
}
notebook > header tab {
    background-color: transparent;
    color: #4a7a52;
    padding: 5px 14px;
    font-size: 11px;
    border: none;
}
notebook > header tab:checked {
    background-color: #162018;
    color: #76ff88;
    border-bottom: 2px solid #38aa55;
}
button.save {
    background-color: #112216;
    color: #76ff88;
    border: 1px solid #2a6636;
    border-radius: 6px;
    padding: 7px;
    font-weight: bold;
    font-size: 11px;
    box-shadow: none;
}
button.save:hover {
    background-color: #1a3a20;
    border-color: #38aa55;
}
switch {
    background-color: #162018;
    border: 1px solid #2a5030;
}
switch:checked {
    background-color: #38aa55;
}
switch slider {
    background-color: #c8e6ca;
    min-width: 16px;
    min-height: 16px;
}
scrolledwindow {
    background-color: transparent;
}
viewport {
    background-color: transparent;
}
"""


class HyprThemer(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="HyprThemer")
        self.set_default_size(377, 492)
        self.set_resizable(False)

        css_provider = Gtk.CssProvider()
        css_provider.load_from_string(CSS)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

        self.state = {
            'active_border_start':   'rgba(76cc88dd)',
            'active_border_end':     'rgba(00bbaadd)',
            'inactive_border_start': 'rgba(38aa55bb)',
            'inactive_border_end':   'rgba(2a8877bb)',
            'border_size':           2,
            'rounding':              12,
            'shadow_color':          'rgba(52cc7799)',
            'shadow_inactive_color': 'rgba(38aa5566)',
            'shadow_range':          35,
            'shadow_render_power':   3,
            'active_opacity':        1.0,
            'inactive_opacity':      0.85,
            'dim_inactive':          True,
            'dim_strength':          0.15,
            'gaps_in':               5,
            'gaps_out':              10,
        }
        self.load_from_conf()

        notebook = Gtk.Notebook()
        notebook.set_tab_pos(Gtk.PositionType.TOP)
        notebook.set_vexpand(True)
        notebook.append_page(self.build_tab_borders(), Gtk.Label(label="Borders"))
        notebook.append_page(self.build_tab_glow(),    Gtk.Label(label="Glow"))
        notebook.append_page(self.build_tab_windows(), Gtk.Label(label="Windows"))

        self.save_btn = Gtk.Button(label="Save to hyprland.conf")
        self.save_btn.add_css_class("save")
        self.save_btn.set_margin_start(10)
        self.save_btn.set_margin_end(10)
        self.save_btn.set_margin_top(6)
        self.save_btn.set_margin_bottom(8)
        self.save_btn.connect("clicked", self.save_to_conf)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        root.append(notebook)
        root.append(self.save_btn)
        self.set_child(root)

    # helpers

    def load_from_conf(self):
        try:
            content = open(CONF_PATH).read()
            def get(pattern, cast, key):
                m = re.search(pattern, content)
                if m:
                    self.state[key] = cast(m.group(1))

            m = re.search(r'col\.active_border\s*=\s*(rgba\(\w+\))\s+(rgba\(\w+\))', content)
            if m:
                self.state['active_border_start'] = m.group(1)
                self.state['active_border_end']   = m.group(2)

            m = re.search(r'col\.inactive_border\s*=\s*(rgba\(\w+\))\s+(rgba\(\w+\))', content)
            if m:
                self.state['inactive_border_start'] = m.group(1)
                self.state['inactive_border_end']   = m.group(2)

            get(r'border_size\s*=\s*(\d+)',          int,   'border_size')
            get(r'rounding\s*=\s*(\d+)',              int,   'rounding')
            get(r'shadow_range\s*=\s*(\d+)',          int,   'shadow_range')

            # shadow block
            m = re.search(r'shadow\s*\{[^}]*?color\s*=\s*(rgba\(\w+\))', content, re.DOTALL)
            if m: self.state['shadow_color'] = m.group(1)
            m = re.search(r'color_inactive\s*=\s*(rgba\(\w+\))', content)
            if m: self.state['shadow_inactive_color'] = m.group(1)
            m = re.search(r'range\s*=\s*(\d+)', content)
            if m: self.state['shadow_range'] = int(m.group(1))
            m = re.search(r'render_power\s*=\s*(\d+)', content)
            if m: self.state['shadow_render_power'] = int(m.group(1))

            get(r'active_opacity\s*=\s*([\d.]+)',     float, 'active_opacity')
            get(r'inactive_opacity\s*=\s*([\d.]+)',   float, 'inactive_opacity')
            get(r'dim_strength\s*=\s*([\d.]+)',       float, 'dim_strength')
            get(r'gaps_in\s*=\s*(\d+)',               int,   'gaps_in')
            get(r'gaps_out\s*=\s*(\d+)',              int,   'gaps_out')

            m = re.search(r'dim_inactive\s*=\s*(true|false)', content)
            if m: self.state['dim_inactive'] = m.group(1) == 'true'
        except Exception as e:
            print(f"[themer] load warning: {e}")

    def scrollwrap(self, box):
        sw = Gtk.ScrolledWindow()
        sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        sw.set_vexpand(True)
        sw.set_child(box)
        return sw

    def section(self, text):
        lbl = Gtk.Label(label=text)
        lbl.set_xalign(0)
        lbl.set_margin_start(12)
        lbl.set_margin_top(8)
        lbl.set_margin_bottom(2)
        lbl.add_css_class("section-label")
        return lbl

    def color_row(self, label_text, state_key, on_change):
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        row.set_margin_start(12)
        row.set_margin_end(12)
        row.set_margin_top(2)
        row.set_margin_bottom(2)

        lbl = Gtk.Label(label=label_text)
        lbl.set_xalign(0)
        lbl.set_hexpand(True)
        row.append(lbl)

        dialog = Gtk.ColorDialog()
        dialog.set_with_alpha(True)
        btn = Gtk.ColorDialogButton(dialog=dialog)
        btn.set_rgba(rgba_to_gdk(self.state[state_key]))

        def notify(b, _param):
            self.state[state_key] = gdk_to_rgba(b.get_rgba())
            on_change()
        btn.connect("notify::rgba", notify)
        row.append(btn)
        return row

    def slider_row(self, label_text, state_key, lo, hi, step, is_float, on_change):
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        row.set_margin_start(12)
        row.set_margin_end(12)
        row.set_margin_top(1)
        row.set_margin_bottom(1)

        lbl = Gtk.Label(label=label_text)
        lbl.set_xalign(0)
        lbl.set_size_request(90, -1)
        row.append(lbl)

        adj = Gtk.Adjustment(value=self.state[state_key], lower=lo, upper=hi, step_increment=step)
        scale = Gtk.Scale(orientation=Gtk.Orientation.HORIZONTAL, adjustment=adj)
        scale.set_hexpand(True)
        scale.set_draw_value(False)
        row.append(scale)

        val_lbl = Gtk.Label()
        val_lbl.add_css_class("value-label")
        fmt = (lambda v: f"{v:.2f}") if is_float else (lambda v: str(int(v)))
        val_lbl.set_label(fmt(self.state[state_key]))

        def changed(s):
            v = s.get_value()
            self.state[state_key] = round(v, 2) if is_float else int(v)
            val_lbl.set_label(fmt(v))
            on_change()
        scale.connect("value-changed", changed)
        row.append(val_lbl)
        return row

    # apply fns

    def _apply_active_border(self):
        hyprctl("general:col.active_border",
                f"{self.state['active_border_start']} {self.state['active_border_end']} 45deg")

    def _apply_inactive_border(self):
        hyprctl("general:col.inactive_border",
                f"{self.state['inactive_border_start']} {self.state['inactive_border_end']} 45deg")

    def _apply_shadow(self):
        hyprctl("decoration:shadow:color",          self.state['shadow_color'])
        hyprctl("decoration:shadow:color_inactive", self.state['shadow_inactive_color'])
        hyprctl("decoration:shadow:range",          str(self.state['shadow_range']))
        hyprctl("decoration:shadow:render_power",   str(self.state['shadow_render_power']))

    # tabs

    def build_tab_borders(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        box.append(self.section("ACTIVE BORDER"))
        box.append(self.color_row("Start",      'active_border_start', self._apply_active_border))
        box.append(self.color_row("End",        'active_border_end',   self._apply_active_border))
        box.append(self.section("INACTIVE BORDER"))
        box.append(self.color_row("Start",      'inactive_border_start', self._apply_inactive_border))
        box.append(self.color_row("End",        'inactive_border_end',   self._apply_inactive_border))
        box.append(self.section("GEOMETRY"))
        box.append(self.slider_row("Border size", 'border_size', 1, 8,  1, False,
            lambda: hyprctl("general:border_size", str(self.state['border_size']))))
        box.append(self.slider_row("Rounding",    'rounding',    0, 25, 1, False,
            lambda: hyprctl("decoration:rounding", str(self.state['rounding']))))
        return self.scrollwrap(box)

    def build_tab_glow(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        box.append(self.section("ACTIVE GLOW"))
        box.append(self.color_row("Color", 'shadow_color', self._apply_shadow))
        box.append(self.section("INACTIVE GLOW"))
        box.append(self.color_row("Color", 'shadow_inactive_color', self._apply_shadow))
        box.append(self.section("SHADOW SHAPE"))
        box.append(self.slider_row("Range",       'shadow_range',        5, 80, 1, False, self._apply_shadow))
        box.append(self.slider_row("Render power",'shadow_render_power', 1,  4, 1, False, self._apply_shadow))
        return self.scrollwrap(box)

    def build_tab_windows(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        box.append(self.section("OPACITY"))
        box.append(self.slider_row("Active",   'active_opacity',   0.3, 1.0, 0.01, True,
            lambda: hyprctl("decoration:active_opacity", str(self.state['active_opacity']))))
        box.append(self.slider_row("Inactive", 'inactive_opacity', 0.3, 1.0, 0.01, True,
            lambda: hyprctl("decoration:inactive_opacity", str(self.state['inactive_opacity']))))

        box.append(self.section("DIMMING"))
        dim_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        dim_row.set_margin_start(12)
        dim_row.set_margin_end(12)
        dim_row.set_margin_top(3)
        dim_row.set_margin_bottom(3)
        dim_lbl = Gtk.Label(label="Dim inactive")
        dim_lbl.set_xalign(0)
        dim_lbl.set_hexpand(True)
        dim_row.append(dim_lbl)
        sw = Gtk.Switch()
        sw.set_active(self.state['dim_inactive'])
        sw.set_valign(Gtk.Align.CENTER)
        def on_dim(s, _):
            self.state['dim_inactive'] = s.get_active()
            hyprctl("decoration:dim_inactive", "true" if s.get_active() else "false")
        sw.connect("state-set", on_dim)
        dim_row.append(sw)
        box.append(dim_row)
        box.append(self.slider_row("Strength", 'dim_strength', 0.0, 0.8, 0.01, True,
            lambda: hyprctl("decoration:dim_strength", str(self.state['dim_strength']))))

        box.append(self.section("GAPS"))
        box.append(self.slider_row("Inner", 'gaps_in',  0, 20, 1, False,
            lambda: hyprctl("general:gaps_in",  str(self.state['gaps_in']))))
        box.append(self.slider_row("Outer", 'gaps_out', 0, 30, 1, False,
            lambda: hyprctl("general:gaps_out", str(self.state['gaps_out']))))
        return self.scrollwrap(box)

    # save

    def save_to_conf(self, _btn):
        try:
            content = open(CONF_PATH).read()
            ab = f"{self.state['active_border_start']} {self.state['active_border_end']} 45deg"
            ib = f"{self.state['inactive_border_start']} {self.state['inactive_border_end']} 45deg"
            content = re.sub(r'col\.active_border\s*=.*',   f"col.active_border = {ab}",   content)
            content = re.sub(r'col\.inactive_border\s*=.*', f"col.inactive_border = {ib}", content)
            content = re.sub(r'(        border_size\s*=\s*)\d+',    f"        border_size = {self.state['border_size']}", content)
            content = re.sub(r'(        rounding\s*=\s*)\d+',       f"        rounding = {self.state['rounding']}", content)
            content = re.sub(r'(        active_opacity\s*=\s*)[\d.]+',   f"        active_opacity = {self.state['active_opacity']:.2f}", content)
            content = re.sub(r'(        inactive_opacity\s*=\s*)[\d.]+', f"        inactive_opacity = {self.state['inactive_opacity']:.2f}", content)
            content = re.sub(r'(        dim_inactive\s*=\s*)\w+',   f"        dim_inactive = {'true' if self.state['dim_inactive'] else 'false'}", content)
            content = re.sub(r'(        dim_strength\s*=\s*)[\d.]+', f"        dim_strength = {self.state['dim_strength']:.2f}", content)
            content = re.sub(r'(        gaps_in\s*=\s*)\d+',  f"        gaps_in = {self.state['gaps_in']}", content)
            content = re.sub(r'(        gaps_out\s*=\s*)\d+', f"        gaps_out = {self.state['gaps_out']}", content)
            # shadow block values
            content = re.sub(r'(            color\s*=\s*)rgba\(\w+\)',          f"            color = {self.state['shadow_color']}", content)
            content = re.sub(r'(            color_inactive\s*=\s*)rgba\(\w+\)', f"            color_inactive = {self.state['shadow_inactive_color']}", content)
            content = re.sub(r'(            range\s*=\s*)\d+',        f"            range = {self.state['shadow_range']}", content)
            content = re.sub(r'(            render_power\s*=\s*)\d+', f"            render_power = {self.state['shadow_render_power']}", content)
            open(CONF_PATH, 'w').write(content)
            self.save_btn.set_label("Saved!")
            GLib.timeout_add(1800, lambda: self.save_btn.set_label("Save to hyprland.conf") or False)
        except Exception as e:
            self.save_btn.set_label(f"Error!")
            print(f"[themer] save error: {e}")


class ThemerApp(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="com.snes.hyprthemer")

    def do_activate(self):
        win = HyprThemer(self)
        win.set_name("hypr-themer")
        win.present()


if __name__ == "__main__":
    ThemerApp().run()
