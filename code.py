import os
import time
import ipaddress
import wifi
import socketpool
import busio
import board
import microcontroller
import terminalio
import ssl
from digitalio import DigitalInOut, Direction
from adafruit_httpserver.server import HTTPServer
from adafruit_httpserver.response import HTTPResponse
from adafruit_onewire.bus import OneWireBus
from adafruit_ds18x20 import DS18X20
import adafruit_requests
import pwmio
import displayio
import terminalio
import adafruit_displayio_ssd1306
from adafruit_display_text import label
from math import sin

#  onboard LED setup
led = DigitalInOut(board.LED)
led.direction = Direction.OUTPUT
led.value = True

# Buzzer
speaker = pwmio.PWMOut(board.GP16, frequency=1930, duty_cycle=0, variable_frequency=True)
speaker.duty_cycle = 0

class AxelF:
    PITCHES = "c,c#,d,d#,e,f,f#,g,g#,a,a#,b".split(",")

    AXEL_F = [
      ("e5", 4),("g5", 2),("e5", 2),("e5",1), ("a5",2),("e5", 2),("d5", 2),
      ("e5", 4),("b5", 2),("e5", 2),("e5",1), ("c6",2),("b5", 2),("g5", 2),
      ("e5", 2),("b5", 2),("e6", 2),("e5",1), ("d5",2),("d5", 1),("b4", 2),("f#5", 2), ("e5", 16)
    ]

    # This is really not how you do it, but it sounds OK
    SPEED = 0.008

    def __init__(self, buzzer):
        self.buzzer = buzzer

    def play_axel(self):
        self.buzzer.duty_cycle = 2 ** 15
        for notename, eigths in self.AXEL_F:
            length = eigths * 0.08

            if notename:
                self.buzzer.duty_cycle = 2 ** 15
                self.buzzer.frequency = self.note(notename)
            else:
                self.buzzer.duty_cycle = 0
            time.sleep(length)
            self.buzzer.duty_cycle = 0
            time.sleep(self.SPEED)
        self.buzzer.duty_cycle = 0

    def note(self, name):
        octave = int(name[-1])
        pitch = self.PITCHES.index(name[:-1].lower())
        return int(440 * 2 ** ((octave - 4) + (pitch - 9) / 12.))

class Alarm:
    def __init__(self, buzzer):
        self.buzzer = buzzer
        self.clock = 0
        self.ringing = False
        self.cycle = True

    def start(self):
        print("starting alarm")
        self.ringing = True
        self.buzzer.frequency = 1930

    def stop(self):
        print("stopping alarm")
        self.ringing = False
        self.buzzer.duty_cycle = 0

    def tick(self):
        if self.ringing:
            t = time.monotonic()
            if (self.clock + 0.3) < t:
                # print("alarm ticked")
                self.clock = t
                if self.cycle:
                    self.buzzer.duty_cycle = 2 ** 15
                    self.cycle = False
                else:
                    self.cycle = True
                    self.buzzer.duty_cycle = 0


# When errors occur during initialization
# that we can't come back from. The user can use turn the device off and on again to start over.
def hang():
    while True:
        speaker.duty_cycle = 2 ** 15
        time.sleep(0.5)
        speaker.duty_cycle = 0
        time.sleep(3)


class Display:
    WIDTH = 128
    HEIGHT = 32
    CHARS_ROW = 20

    def __init__(self):
        displayio.release_displays()
        i2c = busio.I2C(board.GP15, board.GP14)
        display_bus = displayio.I2CDisplay(i2c, device_address=0x3c)
        self.display = adafruit_displayio_ssd1306.SSD1306(display_bus, width=self.WIDTH, height=self.HEIGHT)

        main_group = displayio.Group()
        self.display.show(main_group)

        self.temp_group = displayio.Group()
        self.temp_group.hidden = True
        self.temp_info = label.Label(terminalio.FONT, text="", color=0xFFFF00, x=2, y=28)
        self.labels = (
            label.Label(terminalio.FONT, text="--", color=0xFFFF00, x=8, y=15, scale=2),
            label.Label(terminalio.FONT, text="--", color=0xFFFF00, x=72, y=15, scale=2)
        )
        self.temp_group.append(self.labels[0])
        self.temp_group.append(self.labels[1])
        self.temp_group.append(self.temp_info)
        main_group.append(self.temp_group)

        self.info_group = displayio.Group()
        self.info_lines = (
            label.Label(terminalio.FONT, text="Reticulating", color=0xFFFF00, x=2, y=8),
            label.Label(terminalio.FONT, text="splines...", color=0xFFFF00, x=2, y=20),
        )
        self.info_group.append(self.info_lines[0])
        self.info_group.append(self.info_lines[1])
        main_group.append(self.info_group)

    def update_temps(self, t1, t2, info = ""):
        self.labels[0].text = t1
        self.labels[1].text = t2
        self.temp_info.text = info
        # print("update temps", self.temp_group.hidden, self.info_group.hidden)
        if self.temp_group.hidden:
            self.info_group.hidden = True
            self.temp_group.hidden = False

    def show_info(self):
        if self.info_group.hidden:
            self.temp_group.hidden = True
            self.info_group.hidden = False


    def print(self, text):
        l1 = text[0:self.CHARS_ROW]
        l2 = text[self.CHARS_ROW:self.CHARS_ROW*2]

        if l2 == "":
            # Only one line, lets put it in the middle
            self.info_lines[0].text = ""
            self.info_lines[1].text = l1
        else:
            self.info_lines[0].text = l1
            self.info_lines[1].text = l2
        self.show_info()

    def print_lines(self, l1, l2 = ""):
        self.info_lines[0].text = l1
        self.info_lines[1].text = l2
        self.show_info()


# Setup display
display = Display()
time.sleep(0.5)
display.print("Letar upp temperatur sensorer")
# Temp sensors
# one-wire bus for DS18B20
# ow_bus = OneWireBus(board.GP6) -- v1 build
ow_bus = OneWireBus(board.GP2)

# scan for temp sensor
device_address = ow_bus.scan()

# Sort so we always get the same order
device_address.sort(key=lambda x: " ".join([hex(v) for v in x.rom]))

# for i, d in enumerate(ds18s):
#     print("Device {:>3}".format(i))
#     print("\tSerial Number = ", end="")
#     for byte in d.serial_number:
#         print("0x{:02x} ".format(byte), end="")
#     print("\n\tFamily = 0x{:02x}".format(d.family_code))


ds18s = (
    DS18X20(ow_bus, device_address[0]),
    DS18X20(ow_bus, device_address[1])
)
# Give user a chance to see message
time.sleep(1)

#  connect to network
display.print("Kopplar upp sig mot weefee")


try:
    wifi.radio.connect(os.getenv('WIFI_SSID'), os.getenv('WIFI_PASSWORD'))
except Exception:
    display.print_lines("Kunde inte ansluta","till weefee.")
    hang()

display.print("Ansluten till weefee!")
time.sleep(1)
pool = socketpool.SocketPool(wifi.radio)
server = HTTPServer(pool)
requests = adafruit_requests.Session(pool, ssl.create_default_context())

# STATE
# Target temperature
# TODO: read stored from flash
target_temp = float(os.getenv('TARGET_TEMP') or 90)
warning_temp = float(os.getenv('WARNING_TEMP') or 95)
# print("Target temp is %s" % target_temp)

#  font for HTML
font_family = "monospace"

class Relay:
    def __init__(self, name, ip):
        self.name = name
        self.ip = ip
        self.is_on = False
        self.enabled = False
        self.error = False

    # state is "on" or "off" since that is what the shelly plug wants
    def send(self,state):
        print("Turning relay %s  %s" % (self.name, state))
        turn = "off"
        if state:
            turn = "on"
        response = requests.get("http://%s/relay/0?turn=%s" % (self.ip, turn), timeout=3)
        # print("-" * 40)
        data = response.json()
        # print(data["ison"])
        self.is_on = data["ison"]
        # print("-" * 40)
        response.close()

        # If we got this far all is well
        self.error = False

    def check_relay(self):
        print("Checking if relay is on %s" % self.ip)
        response = requests.get("http://%s/relay/0" % self.ip, timeout=3)
        #print("-" * 40)
        data = response.json()
        #print(data["ison"])
        self.is_on = data["ison"]
        #print("-" * 40)
        response.close()
        self.enabled = True
        self.error = False
        return self.is_on


index = """<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Ta tempen</title>
    <style>
        body, html {
            background: #333;
        }
        div {
            margin: 50px auto;
            color: white;
            font-size: 32px;
            text-align: center;
            font-family: monospace;
        }
    </style>
</head>
<body>
    <div id="temp">--</div>
    <script type="text/javascript">
        const el = document.getElementById("temp")

        const update = () => fetch("/temp")
            .then(res => res.json())
            .then(({ temp, relay }) =>  {
                console.log("temp", temp)
                el.innerHTML = String(temp) + "<br />" + relay

            }).then(() => setTimeout(update, 5000)).catch((e) => { console.error(e); setTimeout(update, 5000) })

        update()

    </script>
</body>
</html>
"""


@server.route("/")
def base(request):  # pylint: disable=unused-argument
    #  serve the HTML f string
    #  with content type text/html
    return HTTPResponse(content_type="text/html", body=index)

@server.route("/temp")
def action_relay_temp(_request):
    print("reading temp")
    return HTTPResponse(content_type="application/json", body='{ "temp1": %s,"temp2": %s, "relay1": "%s", "relay2": "%s" }' % (
        str(ds18s[0].temperature),
        str(ds18s[1].temperature),
        relays[0].is_on and "on" or "off",
        relays[0].is_on and "on" or "off"
    ))

# Setup the two relays
relays = (
    Relay("ettan", os.getenv("PLUG_IP_1")),
    Relay("tvåan", os.getenv("PLUG_IP_2"))
)

for relay in relays:
    # Check relay state
    try:
        display.print_lines("Letar efter relä:", relay.name)
        relay.check_relay()
    except Exception as e:
        print("The error raised is: ", e)
        display.print_lines("Hittade inte relä", relay.name)
        time.sleep(3)

if all(r.enabled == False for r in relays):
    display.print("Hittade inga reläer så jag ger upp")
    hang()

# startup the server
try:
    display.print("Startar web server..")
    server.start(str(wifi.radio.ipv4_address))
    display.print_lines("Server address", "http://%s" % wifi.radio.ipv4_address)
    time.sleep(1)
#  if the server fails to begin, restart the pico w
except OSError:
    display.print("Kunde inte starta web server så jag stänger av mig")
    hang()

clock = time.monotonic()
temp_test = ""

overheat_alarm = False
info_text = "-" * 22
spinner_count = 0

alarm = Alarm(speaker)
axel = AxelF(speaker)

# Beep to say that we're up and running
speaker.duty_cycle = 2 ** 15
speaker.frequency = axel.note("c5") # Yes ugly
time.sleep(0.1)
speaker.frequency = axel.note("g5") # Yes ugly
time.sleep(0.1)
speaker.duty_cycle = 0
speaker.frequency = 1930

warmed_up = [False for x in ds18s]

# main loop
while True:
    #try:

    # Do we have an alarm of some sorts?
    do_we_have_panic = overheat_alarm or any(r.error == True for r in relays)
    if do_we_have_panic and not alarm.ringing:
        alarm.start()
        info_text = "Överhettning"
    elif not do_we_have_panic and alarm.ringing:
        info_text = "-" * 22
        alarm.stop()
    alarm.tick()

    #  every 2 seconds update temp reading
    if (clock + 2) < time.monotonic():
        clock = time.monotonic()

        temp = ds18s[0].temperature
        temp2 = ds18s[1].temperature
        # print("Temp1 is %s℃  target is %s℃" % (str(temp), str(target_temp)))
        # print("Temp2 is %s℃  target is %s℃" % (str(temp2), str(target_temp)))
        # print("Relay 1 is %s" % str(relays[0].is_on))
        # print("Relay 2 is %s" % str(relays[1].is_on))

        # Don't overwrite alarm text
        if not alarm.ringing:
            # Do a small "spinner" so we now it has not just frozen
            info_text = spinner_count * "-" + "*" + (22 - spinner_count) * "-"
            spinner_count += 1
            if spinner_count > 20:
                spinner_count = 0

        # We might only have one of the relays, in that case don't display that temp so the user knows

        display.update_temps(
            relays[0].enabled and str(round(temp,1)) or "--",
            relays[1].enabled and str(round(temp2,1)) or "--",
            info_text
        )

        # Update overheat alarm
        overheat_alarm = temp > warning_temp or temp2 > warning_temp
        print("overheat?", overheat_alarm, temp2, warning_temp)

        for relay, temp, warm, index in zip(relays, (temp, temp2), warmed_up, range(len(relays))):
            if relay.enabled:
                try:
                    if temp >= target_temp and relay.is_on:
                        # Target acquired, turn off
                        print("Turning off")
                        relay.send(False)

                        if not warm:
                            print("warmed up", relay.name)
                            axel_playing = axel.play_axel()
                            warmed_up[index] = True

                    elif temp < target_temp and not relay.is_on:
                        print("Turning on")
                        relay.send(True)
                except Exception:
                    print("Failed to contact relay")
                    alarm.start()
                    info_text = "Relä fel %s" % relay.name
                    relay.error = True

    #  poll the server for incoming/outgoing requests
    server.poll()

    # except Exception as e:
    #     print("Exception", e)
    #     continue
