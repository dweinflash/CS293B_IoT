#!/usr/bin/env python3

import asyncio
import io
import json
import math
import sys

sys.path.append('../lib/')
import flask_helpers
import cozmo

from flask import Flask, request
from PIL import Image, ImageDraw
import requests

import socket
import os
import time as timer

HOST = '192.168.0.13'  # The server's hostname or IP address
PORT = 65432           # The port used by the server
SOCK = None
localfile = 'img.jpeg'
remotehost='pi@192.168.0.13'
remotefile='Documents/CS293B/'
pred = ''
conf = ''
time = ''
mod = 'Rock, Paper, Scissors'

def conn():
  global SOCK
  SOCK = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
  SOCK.connect((HOST, PORT))

def send():
  os.system('scp "%s" "%s:%s"' % (localfile, remotehost, remotefile) )

def classify():
    if (mod == "Rock, Paper, Scissors"):
        SOCK.send(b'clas0')
    else:
        SOCK.send(b'clas1')

def close():
  # Send close msg to server
  SOCK.send(b'exit!') 
  SOCK.close()
  shutdown()

# Annotator for displaying RobotState on top of the camera feed
class RobotStateDisplay(cozmo.annotate.Annotator):

    def apply(self, image, scale):
        d = ImageDraw.Draw(image)

        bounds = [3, 0, image.width, image.height]

        def print_line(text_line):
            text = cozmo.annotate.ImageText(text_line, position=cozmo.annotate.TOP_LEFT, outline_color='black', color='lightblue')
            text.render(d, bounds)
            TEXT_HEIGHT = 11
            bounds[1] += TEXT_HEIGHT

        # Controls
        print_line('W: Forward')
        print_line('S: Reverse')
        print_line('A: Left')
        print_line('D: Right')
        print_line('')
        print_line('T: Camera Up')
        print_line('G: Camera Down')
        print_line('')
        print_line('Shift: Model')
        print_line('Ctrl: Classify')
        print_line('Alt: Shut Down')
        print_line('')

        # Classify
        print_line('Model: <%s>' % mod)
        print_line('Object Classification: <%s>' % pred)
        print_line('Confidence: <%s>' % conf)
        print_line('Time: <%s> ms' % time)


def create_default_image(image_width, image_height):
    '''Create a place-holder PIL image to use until we have a live feed from Cozmo'''
    image_bytes = bytearray([0x70, 0x70, 0x70]) * image_width * image_height
    image = Image.frombytes('RGB', (image_width, image_height), bytes(image_bytes))
    return image

flask_app = Flask(__name__)
remote_control_cozmo = None
_default_camera_image = create_default_image(320, 240)
_is_mouse_look_enabled_by_default = False

class RemoteControlCozmo:

    def __init__(self, coz):
        self.cozmo = coz

        self.drive_forwards = 0
        self.drive_back = 0
        self.turn_left = 0
        self.turn_right = 0
        self.head_up = 0
        self.head_down = 0

        self.go_fast = 0

        self.is_mouse_look_enabled = _is_mouse_look_enabled_by_default
        self.mouse_dir = 0

    def handle_key(self, key_code, is_shift_down, is_ctrl_down, is_alt_down, is_key_down):
        '''Called on any key press or release
           Holding a key down may result in repeated handle_key calls with is_key_down==True
        '''

        # Shut Down
        if is_alt_down:
            close()

        # Update model
        if (is_shift_down):
            self.change_model()

        # Classify image
        if is_ctrl_down:
            #self.take_photos("Paper", 600)
            self.run_classify()

        # Update state of driving intent from keyboard, and if anything changed then call update_driving
        update_driving = True
        if key_code == ord('W'):
            self.drive_forwards = is_key_down
        elif key_code == ord('S'):
            self.drive_back = is_key_down
        elif key_code == ord('A'):
            self.turn_left = is_key_down
        elif key_code == ord('D'):
            self.turn_right = is_key_down
        else:
            update_driving = False

        # Update state of head move intent from keyboard, and if anything changed then call update_head
        update_head = True
        if key_code == ord('T'):
            self.head_up = is_key_down
        elif key_code == ord('G'):
            self.head_down = is_key_down
        else:
            update_head = False

        # Update driving, head and lift as appropriate
        if update_driving:
            self.update_mouse_driving()
        if update_head:
            self.update_head()

    def change_model(self):
        global mod
        if (mod == "ImageNet"):
            mod = "Rock, Paper, Scissors"
        else:
            mod = "ImageNet"

    def run_classify(self):
        global pred
        global conf
        global time

        # save current image
        latest_image = self.cozmo.world.latest_image.raw_image
        latest_image.convert('L').save(localfile)
            
        # send to raspberry pi
        send()
            
        # classify image
        classify()
            
        # results
        data = SOCK.recv(32)
        res = str(data).split(',')
        pred = res[0][2:]
        conf = res[1]
        time = res[2][:-1]
        print('Received', repr(data))

    # Take 300 photos of rock, paper or scissors
    # Pause 1 second between photos
    def take_photos(self, rps, idx):
        path = "/Users/dweinflash/Documents/UCSB/CS293B/Project/TestImages/"
        total = idx + 300
        
        file_start = rps + str(idx) + ".jpeg"
        file_end = rps + str(total) + ".jpeg"

        print(file_start + " - " + file_end)
        timer.sleep(3)

        while (idx < total):
            filename = rps+str(idx)+".jpeg"
            latest_image = self.cozmo.world.latest_image.raw_image
            latest_image.convert('L').save(path+rps+"/"+filename)
            idx += 1
            print(idx)
            timer.sleep(1)

        print("Done!")

    def pick_speed(self, fast_speed, mid_speed, slow_speed):
        if self.go_fast:
            return fast_speed
        return mid_speed

    def update_head(self):
        if not self.is_mouse_look_enabled:
            head_speed = self.pick_speed(2, 1, 0.5)
            head_vel = (self.head_up - self.head_down) * head_speed
            self.cozmo.move_head(head_vel)

    def update_mouse_driving(self):
        drive_dir = (self.drive_forwards - self.drive_back)

        if (drive_dir > 0.1) and self.cozmo.is_on_charger:
            # cozmo is stuck on the charger, and user is trying to drive off - issue an explicit drive off action
            try:
                # don't wait for action to complete - we don't want to block the other updates (camera etc.)
                self.cozmo.drive_off_charger_contacts()
            except cozmo.exceptions.RobotBusy:
                # Robot is busy doing another action - try again next time we get a drive impulse
                pass

        turn_dir = (self.turn_right - self.turn_left) + self.mouse_dir
        if drive_dir < 0:
            # It feels more natural to turn the opposite way when reversing
            turn_dir = -turn_dir

        forward_speed = self.pick_speed(150, 75, 50)
        turn_speed = self.pick_speed(100, 50, 30)

        l_wheel_speed = (drive_dir * forward_speed) + (turn_speed * turn_dir)
        r_wheel_speed = (drive_dir * forward_speed) - (turn_speed * turn_dir)

        self.cozmo.drive_wheels(l_wheel_speed, r_wheel_speed, l_wheel_speed*4, r_wheel_speed*4 )

@flask_app.route("/")
def handle_index_page():
    return '''
    <html>
        <head>
            <title>remote_control_cozmo.py display</title>
        </head>
        <body>
            <h1>CS293B -- Cloud Computing, Edge Computing, and IoT</h1>
            <table>
                <tr>
                    <td valign = top>
                        <img src="cozmoImage" id="cozmoImageId" width=640 height=480>
                        <div id="DebugInfoId"></div>
                    </td>
                </tr>
            </table>

            <script type="text/javascript">

                function postHttpRequest(url, dataSet)
                {
                    var xhr = new XMLHttpRequest();
                    xhr.open("POST", url, true);
                    xhr.send( JSON.stringify( dataSet ) );
                }

                function handleKeyActivity (e, actionType)
                {
                    var keyCode  = (e.keyCode ? e.keyCode : e.which);
                    var hasShift = (e.shiftKey ? 1 : 0)
                    var hasCtrl  = (e.ctrlKey  ? 1 : 0)
                    var hasAlt   = (e.altKey   ? 1 : 0)
                    postHttpRequest(actionType, {keyCode, hasShift, hasCtrl, hasAlt})
                }

                document.addEventListener("keydown", function(e) { handleKeyActivity(e, "keydown") } );
                document.addEventListener("keyup",   function(e) { handleKeyActivity(e, "keyup") } );

            </script>
        </body>
    </html>
    '''

def get_annotated_image():
    image = remote_control_cozmo.cozmo.world.latest_image
    image = image.annotate_image(scale=2)
    return image

def streaming_video(url_root):
    '''Video streaming generator function'''
    try:
        while True:
            if remote_control_cozmo:
                image = get_annotated_image()

                img_io = io.BytesIO()
                image.save(img_io, 'PNG')
                img_io.seek(0)
                yield (b'--frame\r\n'
                    b'Content-Type: image/png\r\n\r\n' + img_io.getvalue() + b'\r\n')
            else:
                asyncio.sleep(.1)
    except cozmo.exceptions.SDKShutdown:
        # Tell the main flask thread to shutdown
        requests.post(url_root + 'shutdown')

@flask_app.route("/cozmoImage")
def handle_cozmoImage():
    return flask_helpers.stream_video(streaming_video, request.url_root)

def handle_key_event(key_request, is_key_down):
    message = json.loads(key_request.data.decode("utf-8"))
    if remote_control_cozmo:
        remote_control_cozmo.handle_key(key_code=(message['keyCode']), is_shift_down=message['hasShift'],
                                        is_ctrl_down=message['hasCtrl'], is_alt_down=message['hasAlt'],
                                        is_key_down=is_key_down)
    return ""

@flask_app.route('/shutdown', methods=['POST'])
def shutdown():
    flask_helpers.shutdown_flask(request)
    return ""

@flask_app.route('/keydown', methods=['POST'])
def handle_keydown():
    '''Called from Javascript whenever a key is down (note: can generate repeat calls if held down)'''
    return handle_key_event(request, is_key_down=True)

@flask_app.route('/keyup', methods=['POST'])
def handle_keyup():
    '''Called from Javascript whenever a key is released'''
    return handle_key_event(request, is_key_down=False)

def run(sdk_conn):
    robot = sdk_conn.wait_for_robot()
    robot.world.image_annotator.add_annotator('robotState', RobotStateDisplay)
    robot.enable_device_imu(True, True, True)

    global remote_control_cozmo
    remote_control_cozmo = RemoteControlCozmo(robot)

    # Turn on image receiving by the camera
    robot.camera.image_stream_enabled = True

    flask_helpers.run_flask(flask_app)

if __name__ == '__main__':
    conn()
    cozmo.setup_basic_logging()
    cozmo.robot.Robot.drive_off_charger_on_connect = False  # RC can drive off charger if required
    try:
        cozmo.connect(run)
    except KeyboardInterrupt as e:
        pass
    except cozmo.ConnectionError as e:
        sys.exit("A connection error occurred: %s" % e)