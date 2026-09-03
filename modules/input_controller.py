"""
Abstraktionsschicht fuer den physischen Drehencoder (KY-040).

Dev-Modus (Ubuntu-Laptop): Es ist keine Hardware vorhanden - die Bedienung
laeuft komplett ueber das Touch/Web-Interface. Diese Klasse tut dann nichts,
ausser eine Meldung auszugeben.

Pi-Modus: Initialisiert den Encoder ueber gpiozero und ruft bei Drehung/Klick
dieselben Callback-Funktionen auf, die auch die Web-UI-Buttons verwenden -
der restliche Code (Flask-Routen, Player-Module) merkt vom Unterschied nichts.

Der gpiozero-Import passiert bewusst erst innerhalb von _init_gpio(), damit
dieses Modul auf dem Ubuntu-Laptop importierbar bleibt, ohne dass dort
gpiozero/lgpio installiert sein muss.
"""


class InputController:
    def __init__(self, platform, on_volume_change=None, on_button_press=None,
                 clk_pin=17, dt_pin=27, sw_pin=22):
        self.platform = platform
        self.on_volume_change = on_volume_change
        self.on_button_press = on_button_press

        if platform == "pi":
            self._init_gpio(clk_pin, dt_pin, sw_pin)
        else:
            print(
                "[InputController] Dev-Modus: kein Drehencoder angeschlossen - "
                "Lautstaerke/Play-Pause laufen ueber das Web-Interface."
            )

    def _init_gpio(self, clk_pin, dt_pin, sw_pin):
        from gpiozero import RotaryEncoder, Button

        self._encoder = RotaryEncoder(dt_pin, clk_pin, max_steps=0)
        self._button = Button(sw_pin)

        self._encoder.when_rotated_clockwise = lambda: self._handle_rotation(-1)
        self._encoder.when_rotated_counter_clockwise = lambda: self._handle_rotation(1)
        self._button.when_pressed = self._handle_button

    def _handle_rotation(self, direction):
        if self.on_volume_change:
            self.on_volume_change(direction)

    def _handle_button(self):
        if self.on_button_press:
            self.on_button_press()
