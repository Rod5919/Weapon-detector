import cv2
import os
import datetime
import time
from flask import render_template, Response, request
from threading import Thread

from ..model.detect import Detect
from .preprocessing.edge_preprocessing import EdgePreprocessor
from .preprocessing.image_preprocessing import ImagePreprocessor

class Camera(Detect):
    def __init__(self, camera: int = 0, image_preprocessing_params: dict = None, edge_preprocessing_params: dict = None):
        self.capture = 0
        self.grey = 0
        self.neg = 0
        self.detect = 0
        self.switch = 1
        self.rec = 0
        self.rec_frame = None
        self.out = None
        self.camera = None
        self.start_time = 0
        self.imagePreprocessor = ImagePreprocessor(image_preprocessing_params)
        self.edgePreprocessor = EdgePreprocessor(edge_preprocessing_params)
        self.setup(camera)
    
    def setup(self, camera: int):
        os.makedirs('images', exist_ok=True)
        os.makedirs('videos', exist_ok=True)

        self.camera = cv2.VideoCapture(camera)
    
    def gen_frames(self):
        """ Generate the frames for the video stream.

        Yields:
            _type_: The frame of the video stream.
        """
        
        # Set the status to standby
        self.pinOut.status = 'standby'
        self.pinOut.write_rgb(False, False, True)
        
        while True:
            success, frame = self.camera.read()
            
            try:
                frame = self.imagePreprocessor.pipeline(frame,
                    self.imagePreprocessor.resize_image,
                    # self.imagePreprocessor.flip_image,
                    self.imagePreprocessor.change_contrast_and_brightness,
                )
                
                # frame = self.edgePreprocessor.pipeline(frame,
                #     self.edgePreprocessor.convert_to_grayscale,
                #     self.edgePreprocessor.apply_clahe,
                #     # self.preprocessor.perform_histogram_equalization,
                #     self.edgePreprocessor.detect_edges,
                #     self.edgePreprocessor.detect_lines,
                #     self.edgePreprocessor.dilate_image,
                #     self.edgePreprocessor.invert_image,
                # )
            except cv2.error:
                print("Camera is not available")
            
            # frame = cv2.flip(frame, 0)
            
            # print("Actual time: ", time.time())
            # print("Start time: ", self.start_time)
            # print("Elapsed time: ", time.time() - self.start_time)
            
            
            if self.pinOut.status == 'standby' and self.pinOut.read_pin():
                self.pinOut.status = 'running'
                print(self.pinOut.status)
                self.pinOut.write_rgb(False, True, True)
                self.detect = 1
                # print('Motion detected')
            
            elif self.pinOut.status == 'running' and (time.time() - self.start_time) > 12:
                # print('No motion detected')
                self.pinOut.status = 'standby'
                print(self.pinOut.status)
                self.pinOut.write_rgb(False, False, True)
                self.start_time = time.time()
                self.detect = 0
            
            elif (self.pinOut.status == 'alarm' and time.time() - self.start_time > 60) or self.pinOut.status == 'password':
                self.pinOut.status = 'sent'
                print(self.pinOut.status)
                self.pinOut.write_rgb(True, False, True)
                self.pinOut.write_relay(0)
                self.start_time = time.time()
                
            elif self.pinOut.status == 'sent' and time.time() - self.start_time > 10:
                self.pinOut.status = 'standby'
                print(self.pinOut.status)
                self.pinOut.write_rgb(False, False, True)
                self.start_time = time.time()
            
            if success:
                if self.detect:
                    detected, results = self.detection(frame)
                    if detected:
                        self.pinOut.status = 'alarm'
                        self.pinOut.write_rgb(True, False, False)
                        self.pinOut.write_relay(1)
                        
                        print("-"*10, results, "-"*10)
                        self.client.new_alert_notification(f"Weapon(s) detected: {results['guns']} gun(s), {results['knives']} knife(s), at {self.client.node_config['location']} in node {self.client.node_config['node_id']}")
                        # raise Exception("Weapon detected")
                        self.detect = 0
                        self.capture = 1
                        self.start_time = time.time()
                if self.capture:
                    self.capture = 0
                    now = datetime.datetime.now()
                    p = os.path.sep.join(['images', "img_{}.png".format(str(now).replace(":", ''))])
                    cv2.imwrite(p, frame)

                if self.rec:
                    self.rec_frame = frame
                    frame = cv2.putText(
                        cv2.flip(frame, 1), "Recording...", (0, 25), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 4
                    )
                    frame = cv2.flip(frame, 1)

                try:
                    #Add results as bounding boxes: {x:..., y:..., width:..., height:..., class:..., confidence:...}
                    # if results:
                    #     for result in results:
                    #         cv2.rectangle(frame, (result['x'], result['y']), (result['x']+result['width'], result['y']+result['height']), (0, 255, 0), 2)
                    #         cv2.putText(frame, f"{result['class']}: {result['confidence']}", (result['x'], result['y']-10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
                    _, buffer = cv2.imencode('.jpg', cv2.flip(frame, 1))
                    frame = buffer.tobytes()
                    yield (b'--frame\r\n'
                           b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')
                except Exception as e:
                    pass
            else:
                pass
    
    def video_feed(self):
        return Response(self.gen_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')
    
    def record(self, out: cv2.VideoWriter):
        while self.rec:
            time.sleep(0.05)
            out.write(self.rec_frame)

    def tasks(self):
        if request.method == 'POST':
            if request.form.get('click') == 'Capture':
                self.capture = 1
            elif request.form.get('rec') == 'Start/Stop Recording':
                self.rec = not self.rec
                if self.rec:
                    now = datetime.datetime.now()
                    fourcc = cv2.VideoWriter_fourcc(*'XVID')
                    self.out = cv2.VideoWriter('./videos/vid_{}.mp4'.format(str(now).replace(":", '')), fourcc, 20.0, (640, 480))
                    # Start new thread for recording the video
                    thread = Thread(target=self.record, args=[self.out, ])
                    thread.start()
                elif not self.rec:
                    self.out.release()

        return render_template('index.html', fps=self.fps, status=self.pinOut.status)
    
    def cleanup(self):
        self.camera.release()
        cv2.destroyAllWindows()