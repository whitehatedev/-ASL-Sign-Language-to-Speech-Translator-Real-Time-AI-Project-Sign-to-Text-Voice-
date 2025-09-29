import sys
import math
import cv2
import numpy as np
import traceback
import pyttsx3
from collections import deque
from PyQt5.QtWidgets import (
    QApplication, QWidget, QLabel, QVBoxLayout, QHBoxLayout,
    QTextEdit, QPushButton, QGridLayout, QSpacerItem, QSizePolicy,
    QComboBox, QCheckBox, QGroupBox, QScrollArea
)
from PyQt5.QtCore import QTimer, Qt, QThread, pyqtSignal
from PyQt5.QtGui import QImage, QPixmap, QFont, QIcon
from cvzone.HandTrackingModule import HandDetector
from keras.models import load_model
from googletrans import Translator, LANGUAGES
from gtts import gTTS
import pygame
import io
import os
import tempfile
import enchant
from string import ascii_uppercase

# Initialize pygame mixer for audio playback
pygame.mixer.init()


# -------------------------
# Utility functions
# -------------------------
def distance(x, y):
    return math.sqrt(((x[0] - y[0]) ** 2) + ((x[1] - y[1]) ** 2))


# -------------------------
# Load model (Keras .h5)
# -------------------------
MODEL_PATH = "A.h5"
try:
    model = load_model(MODEL_PATH)
    print("Loaded model:", MODEL_PATH)
except Exception as e:
    print("Error loading model:", e)
    traceback.print_exc()
    model = None


# Speech worker thread to avoid GUI freezing
class SpeechWorker(QThread):
    finished = pyqtSignal()

    def __init__(self, text, lang_code):
        super().__init__()
        self.text = text
        self.lang_code = lang_code

    def run(self):
        try:
            if self.text.strip():
                # Create gTTS object
                tts = gTTS(text=self.text, lang=self.lang_code, slow=False)

                # Save to temporary file
                with tempfile.NamedTemporaryFile(delete=False, suffix='.mp3') as tmp_file:
                    tts.save(tmp_file.name)
                    tmp_file_path = tmp_file.name

                # Load and play the audio
                pygame.mixer.music.load(tmp_file_path)
                pygame.mixer.music.play()

                # Wait for playback to finish
                while pygame.mixer.music.get_busy():
                    pygame.time.wait(100)

                # Clean up
                os.unlink(tmp_file_path)

        except Exception as e:
            print("Text-to-speech error:", e)

        self.finished.emit()


# -------------------------
# GUI Application
# -------------------------
class SignLanguageApp(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Sign Language to Text Conversion with Translation")
        self.setGeometry(100, 100, 1800, 1000)

        # Camera & detectors
        self.cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
        self.detector = HandDetector(maxHands=1)
        self.hd2 = HandDetector(maxHands=1)
        self.offset = 29

        # Sentence formation variables
        self.current_sentence = ""
        self.last_prediction = ""
        self.prediction_count = 0
        self.PREDICTION_THRESHOLD = 5
        self.last_word = ""
        self.str = " "
        self.word = " "
        self.current_symbol = "Empty"
        self.ten_prev_char = [" "] * 10
        self.count = -1
        self.prev_char = ""

        # Dictionary for word suggestions
        self.ddd = enchant.Dict("en-US")
        self.word1 = " "
        self.word2 = " "
        self.word3 = " "
        self.word4 = " "

        # Translation setup
        self.translator = Translator()
        self.target_language = "hi"  # Default to Hindi
        self.translated_text = ""

        # Language mapping for all Indian regional languages
        self.language_map = {

            "Hindi": "hi",
            "Kannada": "kn",
            "Malayalam": "ml",
            "Marathi": "mr",
            "Punjabi": "pa",
            "Tamil": "ta",
            "Telugu": "te",
            "Urdu": "ur",
            "Bengali": "bn",
            "English": "en",
            "Gujarati": "gu",
        }

        # Language codes for text-to-speech
        self.tts_lang_map = {

            "hi": "hi",  # Hindi
            "kn": "kn",  # Kannada
            "ml": "ml",  # Malayalam
            "mr": "mr",  # Marathi
            "pa": "pa",  # Punjabi
            "ta": "ta",  # Tamil
            "te": "te",  # Telugu
            "ur": "ur", # Urdu
            "bn": "bn",  # Bengali
             "en": "en",  # English
             "gu": "gu" # Gujarati
        }

        # Voice settings
        self.speech_worker = None
        self.enable_voice = True

        # State machine for adding one char per presentation
        self.state = "WAIT_HAND"
        self.current_candidate = None
        self.stable_count = 0
        self.min_stable_frames = 8
        self.absent_count = 0
        self.min_absent_frames = 12

        # Movement trail (optional)
        self.trail_points = deque(maxlen=50)

        # Build UI
        self.init_ui()

        # Timer loop
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_frame)
        self.timer.start(30)

    def init_ui(self):
        main_layout = QHBoxLayout(self)

        # Left column: video feed + skeleton preview
        left_col = QVBoxLayout()

        # Video feed
        video_group = QGroupBox("Camera Feed")
        video_layout = QVBoxLayout()
        self.video_label = QLabel()
        self.video_label.setFixedSize(640, 480)
        self.video_label.setStyleSheet("border:1px solid #333;")
        video_layout.addWidget(self.video_label)
        video_group.setLayout(video_layout)
        left_col.addWidget(video_group)

        # Skeleton preview
        skeleton_group = QGroupBox("Hand Skeleton")
        skeleton_layout = QVBoxLayout()
        self.skeleton_label = QLabel()
        self.skeleton_label.setFixedSize(400, 400)
        self.skeleton_label.setStyleSheet("border:1px solid #2266ff; background: #fff;")
        skeleton_layout.addWidget(self.skeleton_label)
        skeleton_group.setLayout(skeleton_layout)
        left_col.addWidget(skeleton_group)

        main_layout.addLayout(left_col, 50)

        # Middle column: detected text and controls
        middle_col = QVBoxLayout()

        # Current character
        char_group = QGroupBox("Detected Character")
        char_layout = QVBoxLayout()
        self.char_label = QLabel("Empty")
        self.char_label.setFont(QFont("Arial", 24, QFont.Bold))
        self.char_label.setAlignment(Qt.AlignCenter)
        self.char_label.setStyleSheet("background: #f0f0f0; padding: 10px;")
        char_layout.addWidget(self.char_label)
        char_group.setLayout(char_layout)
        middle_col.addWidget(char_group)

        # Detected sentence
        sentence_group = QGroupBox("Detected Sentence")
        sentence_layout = QVBoxLayout()
        self.text_edit = QTextEdit()
        self.text_edit.setReadOnly(False)
        self.text_edit.setFont(QFont("Arial", 14))
        self.text_edit.setMinimumHeight(100)
        self.text_edit.textChanged.connect(self.translate_text)
        sentence_layout.addWidget(self.text_edit)
        sentence_group.setLayout(sentence_layout)
        middle_col.addWidget(sentence_group)

        # Word suggestions
        suggestions_group = QGroupBox("Word Suggestions")
        suggestions_layout = QGridLayout()
        self.suggestion_btn1 = QPushButton(" ")
        self.suggestion_btn2 = QPushButton(" ")
        self.suggestion_btn3 = QPushButton(" ")
        self.suggestion_btn4 = QPushButton(" ")

        for btn in [self.suggestion_btn1, self.suggestion_btn2,
                    self.suggestion_btn3, self.suggestion_btn4]:
            btn.setFont(QFont("Arial", 12))
            btn.setMinimumHeight(40)

        self.suggestion_btn1.clicked.connect(lambda: self.use_suggestion(0))
        self.suggestion_btn2.clicked.connect(lambda: self.use_suggestion(1))
        self.suggestion_btn3.clicked.connect(lambda: self.use_suggestion(2))
        self.suggestion_btn4.clicked.connect(lambda: self.use_suggestion(3))

        suggestions_layout.addWidget(self.suggestion_btn1, 0, 0)
        suggestions_layout.addWidget(self.suggestion_btn2, 0, 1)
        suggestions_layout.addWidget(self.suggestion_btn3, 1, 0)
        suggestions_layout.addWidget(self.suggestion_btn4, 1, 1)
        suggestions_group.setLayout(suggestions_layout)
        middle_col.addWidget(suggestions_group)

        # Control buttons
        controls_group = QGroupBox("Controls")
        controls_layout = QHBoxLayout()
        self.clear_btn = QPushButton("Clear Text")
        self.clear_btn.clicked.connect(self.clear_sentence)
        self.speak_btn = QPushButton("Speak Text")
        self.speak_btn.clicked.connect(self.speak_text)
        controls_layout.addWidget(self.clear_btn)
        controls_layout.addWidget(self.speak_btn)
        controls_group.setLayout(controls_layout)
        middle_col.addWidget(controls_group)

        main_layout.addLayout(middle_col, 25)

        # Right column: translation
        right_col = QVBoxLayout()

        # Translation settings
        translation_settings_group = QGroupBox("Translation Settings")
        translation_settings_layout = QVBoxLayout()

        # Language selection with scroll area
        lang_layout = QHBoxLayout()
        lang_label = QLabel("Translate to:")
        lang_label.setFont(QFont("Arial", 12))
        lang_layout.addWidget(lang_label)

        self.lang_combo = QComboBox()
        # Add all Indian languages
        languages = [
              "Hindi", "Kannada","Malayalam", "Marathi", "Punjabi",  "Tamil", "Telugu", "Urdu", "Bengali", "English","Gujarati"
        ]
        self.lang_combo.addItems(languages)
        self.lang_combo.currentTextChanged.connect(self.change_language)
        self.lang_combo.setFont(QFont("Arial", 12))
        lang_layout.addWidget(self.lang_combo)
        translation_settings_layout.addLayout(lang_layout)

        # Voice settings
        voice_layout = QHBoxLayout()
        self.voice_checkbox = QCheckBox("Enable Voice Output")
        self.voice_checkbox.setChecked(True)
        self.voice_checkbox.stateChanged.connect(self.toggle_voice)
        self.voice_checkbox.setFont(QFont("Arial", 12))
        voice_layout.addWidget(self.voice_checkbox)

        self.speak_translation_btn = QPushButton("Speak Translation")
        self.speak_translation_btn.clicked.connect(self.speak_translation)
        self.speak_translation_btn.setFont(QFont("Arial", 12))
        voice_layout.addWidget(self.speak_translation_btn)

        translation_settings_layout.addLayout(voice_layout)
        translation_settings_group.setLayout(translation_settings_layout)
        right_col.addWidget(translation_settings_group)

        # Translation output
        translation_group = QGroupBox("Translation")
        translation_layout = QVBoxLayout()
        self.translation_display = QTextEdit()
        self.translation_display.setReadOnly(True)
        self.translation_display.setFont(QFont("Arial", 14))
        self.translation_display.setMinimumHeight(200)
        translation_layout.addWidget(self.translation_display)
        translation_group.setLayout(translation_layout)
        right_col.addWidget(translation_group)

        # Sign reference
        sign_reference_group = QGroupBox("Sign Reference (A-Z)")
        sign_reference_layout = QGridLayout()

        for i in range(26):
            lab = QLabel(chr(65 + i))
            lab.setAlignment(Qt.AlignCenter)
            lab.setFixedSize(30, 30)
            lab.setStyleSheet("background:#eee; border:1px solid #ccc; padding:2px;")
            r = i // 6
            c = i % 6
            sign_reference_layout.addWidget(lab, r, c)

        sign_reference_group.setLayout(sign_reference_layout)
        right_col.addWidget(sign_reference_group)

        main_layout.addLayout(right_col, 25)

    def use_suggestion(self, index):
        suggestions = [self.word1, self.word2, self.word3, self.word4]
        if index < len(suggestions) and suggestions[index].strip():
            # Replace the last word with the suggestion
            words = self.str.strip().split()
            if words:
                words[-1] = suggestions[index]
            else:
                words = [suggestions[index]]

            self.str = " ".join(words)
            self.text_edit.setPlainText(self.str)
            self.translate_text()

    def change_language(self, language):
        self.target_language = self.language_map[language]
        self.translate_text()

    def toggle_voice(self, state):
        self.enable_voice = (state == Qt.Checked)

    def speak_translation(self):
        if self.translated_text.strip():
            self.speak_text(self.translated_text, self.target_language)

    def speak_text(self, text, lang_code):
        if not self.enable_voice:
            return

        # Stop any ongoing speech
        if pygame.mixer.music.get_busy():
            pygame.mixer.music.stop()

        # Use the speech worker thread to avoid freezing the GUI
        self.speech_worker = SpeechWorker(text, self.tts_lang_map.get(lang_code, "en"))
        self.speech_worker.start()

    def translate_text(self):
        text_to_translate = self.text_edit.toPlainText()
        if text_to_translate.strip() and self.target_language != "en":
            try:
                translated = self.translator.translate(text_to_translate, dest=self.target_language)
                self.translated_text = translated.text
                self.translation_display.setPlainText(self.translated_text)

                # Check if a new word has been completed for voice output
                words = text_to_translate.split()
                if words and words[-1] != self.last_word:
                    self.last_word = words[-1]
                    # Speak the newly completed word
                    word_translation = self.translator.translate(self.last_word, dest=self.target_language).text
                    self.speak_text(word_translation, self.target_language)

            except Exception as e:
                print("Translation error:", e)
                self.translation_display.setPlainText("Translation error. Please try again.")
        elif self.target_language == "en":
            self.translated_text = text_to_translate
            self.translation_display.setPlainText(text_to_translate)

            # Check if a new word has been completed for voice output
            words = text_to_translate.split()
            if words and words[-1] != self.last_word:
                self.last_word = words[-1]
                self.speak_text(self.last_word, "en")
        else:
            self.translation_display.setPlainText("")
            self.last_word = ""

    def clear_sentence(self):
        self.str = " "
        self.text_edit.setPlainText(self.str)
        self.translation_display.setPlainText("")
        self.last_word = ""
        self.word1 = " "
        self.word2 = " "
        self.word3 = " "
        self.word4 = " "
        self.update_suggestion_buttons()

    def update_suggestion_buttons(self):
        self.suggestion_btn1.setText(self.word1)
        self.suggestion_btn2.setText(self.word2)
        self.suggestion_btn3.setText(self.word3)
        self.suggestion_btn4.setText(self.word4)

    def predict(self, test_image, pts):
        white = test_image
        white = white.reshape(1, 400, 400, 3)
        prob = np.array(model.predict(white, verbose=0)[0], dtype='float32')
        ch1 = np.argmax(prob, axis=0)
        prob[ch1] = 0
        ch2 = np.argmax(prob, axis=0)
        prob[ch2] = 0
        ch3 = np.argmax(prob, axis=0)
        prob[ch3] = 0

        pl = [ch1, ch2]

        # All the condition checks from the original code
        # Condition for [Aemnst]
        l = [[5, 2], [5, 3], [3, 5], [3, 6], [3, 0], [3, 2], [6, 4], [6, 1], [6, 2], [6, 6], [6, 7], [6, 0], [6, 5],
             [4, 1], [1, 0], [1, 1], [6, 3], [1, 6], [5, 6], [5, 1], [4, 5], [1, 4], [1, 5], [2, 0], [2, 6], [4, 6],
             [1, 0], [5, 7], [1, 6], [6, 1], [7, 6], [2, 5], [7, 1], [5, 4], [7, 0], [7, 5], [7, 2]]
        if pl in l:
            if (pts[6][1] < pts[8][1] and pts[10][1] < pts[12][1] and pts[14][1] < pts[16][1] and pts[18][1] < pts[20][
                1]):
                ch1 = 0

        # Condition for [o][s]
        l = [[2, 2], [2, 1]]
        if pl in l:
            if (pts[5][0] < pts[4][0]):
                ch1 = 0

        # Condition for [c0][aemnst]
        l = [[0, 0], [0, 6], [0, 2], [0, 5], [0, 1], [0, 7], [5, 2], [7, 6], [7, 1]]
        pl = [ch1, ch2]
        if pl in l:
            if (pts[0][0] > pts[8][0] and pts[0][0] > pts[4][0] and pts[0][0] > pts[12][0] and pts[0][0] > pts[16][
                0] and pts[0][0] > pts[20][0]) and pts[5][0] > pts[4][0]:
                ch1 = 2

        # Condition for [c0][aemnst]
        l = [[6, 0], [6, 6], [6, 2]]
        pl = [ch1, ch2]
        if pl in l:
            if distance(pts[8], pts[16]) < 52:
                ch1 = 2

        # Condition for [gh][bdfikruvw]
        l = [[1, 4], [1, 5], [1, 6], [1, 3], [1, 0]]
        pl = [ch1, ch2]

        if pl in l:
            if pts[6][1] > pts[8][1] and pts[14][1] < pts[16][1] and pts[18][1] < pts[20][1] and pts[0][0] < pts[8][
                0] and pts[0][0] < pts[12][0] and pts[0][0] < pts[16][0] and pts[0][0] < pts[20][0]:
                ch1 = 3

        # Con for [gh][l]
        l = [[4, 6], [4, 1], [4, 5], [4, 3], [4, 7]]
        pl = [ch1, ch2]
        if pl in l:
            if pts[4][0] > pts[0][0]:
                ch1 = 3

        # Con for [gh][pqz]
        l = [[5, 3], [5, 0], [5, 7], [5, 4], [5, 2], [5, 1], [5, 5]]
        pl = [ch1, ch2]
        if pl in l:
            if pts[2][1] + 15 < pts[16][1]:
                ch1 = 3

        # Con for [l][x]
        l = [[6, 4], [6, 1], [6, 2]]
        pl = [ch1, ch2]
        if pl in l:
            if distance(pts[4], pts[11]) > 55:
                ch1 = 4

        # Con for [l][d]
        l = [[1, 4], [1, 6], [1, 1]]
        pl = [ch1, ch2]
        if pl in l:
            if (distance(pts[4], pts[11]) > 50) and (
                    pts[6][1] > pts[8][1] and pts[10][1] < pts[12][1] and pts[14][1] < pts[16][1] and pts[18][1] <
                    pts[20][1]):
                ch1 = 4

        # Con for [l][gh]
        l = [[3, 6], [3, 4]]
        pl = [ch1, ch2]
        if pl in l:
            if (pts[4][0] < pts[0][0]):
                ch1 = 4

        # Con for [l][c0]
        l = [[2, 2], [2, 5], [2, 4]]
        pl = [ch1, ch2]
        if pl in l:
            if (pts[1][0] < pts[12][0]):
                ch1 = 4

        # Con for [gh][z]
        l = [[3, 6], [3, 5], [3, 4]]
        pl = [ch1, ch2]
        if pl in l:
            if (pts[6][1] > pts[8][1] and pts[10][1] < pts[12][1] and pts[14][1] < pts[16][1] and pts[18][1] < pts[20][
                1]) and pts[4][1] > pts[10][1]:
                ch1 = 5

        # Con for [gh][pq]
        l = [[3, 2], [3, 1], [3, 6]]
        pl = [ch1, ch2]
        if pl in l:
            if pts[4][1] + 17 > pts[8][1] and pts[4][1] + 17 > pts[12][1] and pts[4][1] + 17 > pts[16][1] and pts[4][
                1] + 17 > pts[20][1]:
                ch1 = 5

        # Con for [l][pqz]
        l = [[4, 4], [4, 5], [4, 2], [7, 5], [7, 6], [7, 0]]
        pl = [ch1, ch2]
        if pl in l:
            if pts[4][0] > pts[0][0]:
                ch1 = 5

        # Con for [pqz][aemnst]
        l = [[0, 2], [0, 6], [0, 1], [0, 5], [0, 0], [0, 7], [0, 4], [0, 3], [2, 7]]
        pl = [ch1, ch2]
        if pl in l:
            if pts[0][0] < pts[8][0] and pts[0][0] < pts[12][0] and pts[0][0] < pts[16][0] and pts[0][0] < pts[20][0]:
                ch1 = 5

        # Con for [pqz][yj]
        l = [[5, 7], [5, 2], [5, 6]]
        pl = [ch1, ch2]
        if pl in l:
            if pts[3][0] < pts[0][0]:
                ch1 = 7

        # Con for [l][yj]
        l = [[4, 6], [4, 2], [4, 4], [4, 1], [4, 5], [4, 7]]
        pl = [ch1, ch2]
        if pl in l:
            if pts[6][1] < pts[8][1]:
                ch1 = 7

        # Con for [x][yj]
        l = [[6, 7], [0, 7], [0, 1], [0, 0], [6, 4], [6, 6], [6, 5], [6, 1]]
        pl = [ch1, ch2]
        if pl in l:
            if pts[18][1] > pts[20][1]:
                ch1 = 7

        # Condition for [x][aemnst]
        l = [[0, 4], [0, 2], [0, 3], [0, 1], [0, 6]]
        pl = [ch1, ch2]
        if pl in l:
            if pts[5][0] > pts[16][0]:
                ch1 = 6

        # Condition for [yj][x]
        l = [[7, 2]]
        pl = [ch1, ch2]
        if pl in l:
            if pts[18][1] < pts[20][1] and pts[8][1] < pts[10][1]:
                ch1 = 6

        # Condition for [c0][x]
        l = [[2, 1], [2, 2], [2, 6], [2, 7], [2, 0]]
        pl = [ch1, ch2]
        if pl in l:
            if distance(pts[8], pts[16]) > 50:
                ch1 = 6

        # Con for [l][x]
        l = [[4, 6], [4, 2], [4, 1], [4, 4]]
        pl = [ch1, ch2]
        if pl in l:
            if distance(pts[4], pts[11]) < 60:
                ch1 = 6

        # Con for [x][d]
        l = [[1, 4], [1, 6], [1, 0], [1, 2]]
        pl = [ch1, ch2]
        if pl in l:
            if pts[5][0] - pts[4][0] - 15 > 0:
                ch1 = 6

        # Con for [b][pqz]
        l = [[5, 0], [5, 1], [5, 4], [5, 5], [5, 6], [6, 1], [7, 6], [0, 2], [7, 1], [7, 4], [6, 6], [7, 2], [5, 0],
             [6, 3], [6, 4], [7, 5], [7, 2]]
        pl = [ch1, ch2]
        if pl in l:
            if (pts[6][1] > pts[8][1] and pts[10][1] > pts[12][1] and pts[14][1] > pts[16][1] and pts[18][1] > pts[20][
                1]):
                ch1 = 1

        # Con for [f][pqz]
        l = [[6, 1], [6, 0], [0, 3], [6, 4], [2, 2], [0, 6], [6, 2], [7, 6], [4, 6], [4, 1], [4, 2], [0, 2], [7, 1],
             [7, 4], [6, 6], [7, 2], [7, 5], [7, 2]]
        pl = [ch1, ch2]
        if pl in l:
            if (pts[6][1] < pts[8][1] and pts[10][1] > pts[12][1] and pts[14][1] > pts[16][1] and pts[18][1] > pts[20][
                1]):
                ch1 = 1

        l = [[6, 1], [6, 0], [4, 2], [4, 1], [4, 6], [4, 4]]
        pl = [ch1, ch2]
        if pl in l:
            if (pts[10][1] > pts[12][1] and pts[14][1] > pts[16][1] and pts[18][1] > pts[20][1]):
                ch1 = 1

        # Con for [d][pqz]
        l = [[5, 0], [3, 4], [3, 0], [3, 1], [3, 5], [5, 5], [5, 4], [5, 1], [7, 6]]
        pl = [ch1, ch2]
        if pl in l:
            if ((pts[6][1] > pts[8][1] and pts[10][1] < pts[12][1] and pts[14][1] < pts[16][1] and pts[18][1] < pts[20][
                1]) and (pts[2][0] < pts[0][0]) and pts[4][1] > pts[14][1]):
                ch1 = 1

        l = [[4, 1], [4, 2], [4, 4]]
        pl = [ch1, ch2]
        if pl in l:
            if (distance(pts[4], pts[11]) < 50) and (
                    pts[6][1] > pts[8][1] and pts[10][1] < pts[12][1] and pts[14][1] < pts[16][1] and pts[18][1] <
                    pts[20][1]):
                ch1 = 1

        l = [[3, 4], [3, 0], [3, 1], [3, 5], [3, 6]]
        pl = [ch1, ch2]
        if pl in l:
            if ((pts[6][1] > pts[8][1] and pts[10][1] < pts[12][1] and pts[14][1] < pts[16][1] and pts[18][1] < pts[20][
                1]) and (pts[2][0] < pts[0][0]) and pts[14][1] < pts[4][1]):
                ch1 = 1

        l = [[6, 6], [6, 4], [6, 1], [6, 2]]
        pl = [ch1, ch2]
        if pl in l:
            if pts[5][0] - pts[4][0] - 15 < 0:
                ch1 = 1

        # Con for [i][pqz]
        l = [[5, 4], [5, 5], [5, 1], [0, 3], [0, 7], [5, 0], [0, 2], [6, 2], [7, 5], [7, 1], [7, 6], [7, 7]]
        pl = [ch1, ch2]
        if pl in l:
            if ((pts[6][1] < pts[8][1] and pts[10][1] < pts[12][1] and pts[14][1] < pts[16][1] and pts[18][1] > pts[20][
                1])):
                ch1 = 1

        # Con for [yj][bfdi]
        l = [[1, 5], [1, 7], [1, 1], [1, 6], [1, 3], [1, 0]]
        pl = [ch1, ch2]
        if pl in l:
            if (pts[4][0] < pts[5][0] + 15) and ((
                    pts[6][1] < pts[8][1] and pts[10][1] < pts[12][1] and pts[14][1] < pts[16][1] and pts[18][1] >
                    pts[20][1])):
                ch1 = 7

        # Con for [uvr]
        l = [[5, 5], [5, 0], [5, 4], [5, 1], [4, 6], [4, 1], [7, 6], [3, 0], [3, 5]]
        pl = [ch1, ch2]
        if pl in l:
            if ((pts[6][1] > pts[8][1] and pts[10][1] > pts[12][1] and pts[14][1] < pts[16][1] and pts[18][1] < pts[20][
                1])) and pts[4][1] > pts[14][1]:
                ch1 = 1

        # Con for [w]
        fg = 13
        l = [[3, 5], [3, 0], [3, 6], [5, 1], [4, 1], [2, 0], [5, 0], [5, 5]]
        pl = [ch1, ch2]
        if pl in l:
            if not (pts[0][0] + fg < pts[8][0] and pts[0][0] + fg < pts[12][0] and pts[0][0] + fg < pts[16][0] and
                    pts[0][0] + fg < pts[20][0]) and not (
                    pts[0][0] > pts[8][0] and pts[0][0] > pts[12][0] and pts[0][0] > pts[16][0] and pts[0][0] > pts[20][
                0]) and distance(pts[4], pts[11]) < 50:
                ch1 = 1

        # Con for [w]
        l = [[5, 0], [5, 5], [0, 1]]
        pl = [ch1, ch2]
        if pl in l:
            if pts[6][1] > pts[8][1] and pts[10][1] > pts[12][1] and pts[14][1] > pts[16][1]:
                ch1 = 1

        # -------------------------condn for 8 groups  ends

        # -------------------------condn for subgroups  starts
        if ch1 == 0:
            ch1 = 'S'
            if pts[4][0] < pts[6][0] and pts[4][0] < pts[10][0] and pts[4][0] < pts[14][0] and pts[4][0] < pts[18][0]:
                ch1 = 'A'
            if pts[4][0] > pts[6][0] and pts[4][0] < pts[10][0] and pts[4][0] < pts[14][0] and pts[4][0] < pts[18][
                0] and pts[4][1] < pts[14][1] and pts[4][1] < pts[18][1]:
                ch1 = 'T'
            if pts[4][1] > pts[8][1] and pts[4][1] > pts[12][1] and pts[4][1] > pts[16][1] and pts[4][1] > pts[20][1]:
                ch1 = 'E'
            if pts[4][0] > pts[6][0] and pts[4][0] > pts[10][0] and pts[4][0] > pts[14][0] and pts[4][1] < pts[18][1]:
                ch1 = 'M'
            if pts[4][0] > pts[6][0] and pts[4][0] > pts[10][0] and pts[4][1] < pts[18][1] and pts[4][1] < pts[14][1]:
                ch1 = 'N'

        if ch1 == 2:
            if distance(pts[12], pts[4]) > 42:
                ch1 = 'C'
            else:
                ch1 = 'O'

        if ch1 == 3:
            if distance(pts[8], pts[12]) > 72:
                ch1 = 'G'
            else:
                ch1 = 'H'

        if ch1 == 7:
            if distance(pts[8], pts[4]) > 42:
                ch1 = 'Y'
            else:
                ch1 = 'J'

        if ch1 == 4:
            ch1 = 'L'

        if ch1 == 6:
            ch1 = 'X'

        if ch1 == 5:
            if pts[4][0] > pts[12][0] and pts[4][0] > pts[16][0] and pts[4][0] > pts[20][0]:
                if pts[8][1] < pts[5][1]:
                    ch1 = 'Z'
                else:
                    ch1 = 'Q'
            else:
                ch1 = 'P'

        if ch1 == 1:
            if (pts[6][1] > pts[8][1] and pts[10][1] > pts[12][1] and pts[14][1] > pts[16][1] and pts[18][1] > pts[20][
                1]):
                ch1 = 'B'
            if (pts[6][1] > pts[8][1] and pts[10][1] < pts[12][1] and pts[14][1] < pts[16][1] and pts[18][1] < pts[20][
                1]):
                ch1 = 'D'
            if (pts[6][1] < pts[8][1] and pts[10][1] > pts[12][1] and pts[14][1] > pts[16][1] and pts[18][1] > pts[20][
                1]):
                ch1 = 'F'
            if (pts[6][1] < pts[8][1] and pts[10][1] < pts[12][1] and pts[14][1] < pts[16][1] and pts[18][1] > pts[20][
                1]):
                ch1 = 'I'
            if (pts[6][1] > pts[8][1] and pts[10][1] > pts[12][1] and pts[14][1] > pts[16][1] and pts[18][1] < pts[20][
                1]):
                ch1 = 'W'
            if (pts[6][1] > pts[8][1] and pts[10][1] > pts[12][1] and pts[14][1] < pts[16][1] and pts[18][1] < pts[20][
                1]) and pts[4][1] < pts[9][1]:
                ch1 = 'K'
            if ((distance(pts[8], pts[12]) - distance(pts[6], pts[10])) < 8) and (
                    pts[6][1] > pts[8][1] and pts[10][1] > pts[12][1] and pts[14][1] < pts[16][1] and pts[18][1] <
                    pts[20][1]):
                ch1 = 'U'
            if ((distance(pts[8], pts[12]) - distance(pts[6], pts[10])) >= 8) and (
                    pts[6][1] > pts[8][1] and pts[10][1] > pts[12][1] and pts[14][1] < pts[16][1] and pts[18][1] <
                    pts[20][1]) and (pts[4][1] > pts[9][1]):
                ch1 = 'V'
            if (pts[8][0] > pts[12][0]) and (
                    pts[6][1] > pts[8][1] and pts[10][1] > pts[12][1] and pts[14][1] < pts[16][1] and pts[18][1] <
                    pts[20][1]):
                ch1 = 'R'

        if ch1 == 1 or ch1 == 'E' or ch1 == 'S' or ch1 == 'X' or ch1 == 'Y' or ch1 == 'B':
            if (pts[6][1] > pts[8][1] and pts[10][1] < pts[12][1] and pts[14][1] < pts[16][1] and pts[18][1] > pts[20][
                1]):
                ch1 = " "

        if ch1 == 'E' or ch1 == 'Y' or ch1 == 'B':
            if (pts[4][0] < pts[5][0]) and (
                    pts[6][1] > pts[8][1] and pts[10][1] > pts[12][1] and pts[14][1] > pts[16][1] and pts[18][1] >
                    pts[20][1]):
                ch1 = "next"

        if ch1 == 'Next' or 'B' or 'C' or 'H' or 'F' or 'X':
            if (pts[0][0] > pts[8][0] and pts[0][0] > pts[12][0] and pts[0][0] > pts[16][0] and pts[0][0] > pts[20][
                0]) and (
                    pts[4][1] < pts[8][1] and pts[4][1] < pts[12][1] and pts[4][1] < pts[16][1] and pts[4][1] < pts[20][
                1]) and (
                    pts[4][1] < pts[6][1] and pts[4][1] < pts[10][1] and pts[4][1] < pts[14][1] and pts[4][1] < pts[18][
                1]):
                ch1 = 'Backspace'

        if ch1 == "next" and self.prev_char != "next":
            if self.ten_prev_char[(self.count - 2) % 10] != "next":
                if self.ten_prev_char[(self.count - 2) % 10] == "Backspace":
                    self.str = self.str[0:-1]
                else:
                    if self.ten_prev_char[(self.count - 2) % 10] != "Backspace":
                        self.str = self.str + self.ten_prev_char[(self.count - 2) % 10]
            else:
                if self.ten_prev_char[(self.count - 0) % 10] != "Backspace":
                    self.str = self.str + self.ten_prev_char[(self.count - 0) % 10]

        if ch1 == "  " and self.prev_char != "  ":
            self.str = self.str + "  "

        self.prev_char = ch1
        self.current_symbol = ch1
        self.count += 1
        self.ten_prev_char[self.count % 10] = ch1

        if len(self.str.strip()) != 0:
            st = self.str.rfind(" ")
            ed = len(self.str)
            word = self.str[st + 1:ed]
            self.word = word
            if len(word.strip()) != 0:
                self.ddd.check(word)
                lenn = len(self.ddd.suggest(word))
                if lenn >= 4:
                    self.word4 = self.ddd.suggest(word)[3]
                else:
                    self.word4 = " "

                if lenn >= 3:
                    self.word3 = self.ddd.suggest(word)[2]
                else:
                    self.word3 = " "

                if lenn >= 2:
                    self.word2 = self.ddd.suggest(word)[1]
                else:
                    self.word2 = " "

                if lenn >= 1:
                    self.word1 = self.ddd.suggest(word)[0]
                else:
                    self.word1 = " "
            else:
                self.word1 = " "
                self.word2 = " "
                self.word3 = " "
                self.word4 = " "

        self.update_suggestion_buttons()
        self.text_edit.setPlainText(self.str)
        self.char_label.setText(str(ch1))
        self.translate_text()

        return ch1

    def update_frame(self):
        ret, frame = self.cap.read()
        if not ret:
            return

        frame = cv2.flip(frame, 1)
        h, w, _ = frame.shape

        # detection box (center)
        box_size = 300
        box_x1 = w // 2 - box_size // 2
        box_y1 = h // 2 - box_size // 2
        box_x2 = box_x1 + box_size
        box_y2 = box_y1 + box_size
        cv2.rectangle(frame, (box_x1, box_y1), (box_x2, box_y2), (0, 200, 0), 2)

        # find hands
        hands, img = self.detector.findHands(frame, draw=False, flipType=True)
        hand_in_box = False
        skeleton_viz = np.ones((400, 400, 3), dtype=np.uint8) * 255
        pred_label = None
        pred_conf = 0.0

        if hands and model is not None:
            hand = hands[0]
            x, y, wbox, hbox = hand['bbox']
            cx = x + wbox // 2
            cy = y + hbox // 2
            hand_in_box = (box_x1 < cx < box_x2 and box_y1 < cy < box_y2)

            # process crop and landmarks via hd2
            y1 = max(0, y - self.offset)
            y2 = min(frame.shape[0], y + hbox + self.offset)
            x1 = max(0, x - self.offset)
            x2 = min(frame.shape[1], x + wbox + self.offset)

            if y2 > y1 and x2 > x1:
                image = frame[y1:y2, x1:x2]
                if image.size > 0:
                    handz, _ = self.hd2.findHands(image, draw=False, flipType=True)
                    if handz:
                        pts = handz[0]['lmList']
                        if len(pts) >= 21:
                            # create white 400x400 and draw skeleton & numbers
                            white = 255 * np.ones((400, 400, 3), np.uint8)
                            os_x = ((400 - wbox) // 2) - 15
                            os_y = ((400 - hbox) // 2) - 15

                            # Draw finger lines (thumb, index, middle, ring, pinky)
                            try:
                                for t in range(0, 4):
                                    cv2.line(white,
                                             (pts[t][0] + os_x, pts[t][1] + os_y),
                                             (pts[t + 1][0] + os_x, pts[t + 1][1] + os_y),
                                             (0, 255, 0), 3)
                                for t in range(5, 8):
                                    cv2.line(white,
                                             (pts[t][0] + os_x, pts[t][1] + os_y),
                                             (pts[t + 1][0] + os_x, pts[t + 1][1] + os_y),
                                             (0, 255, 0), 3)
                                for t in range(9, 12):
                                    cv2.line(white,
                                             (pts[t][0] + os_x, pts[t][1] + os_y),
                                             (pts[t + 1][0] + os_x, pts[t + 1][1] + os_y),
                                             (0, 255, 0), 3)
                                for t in range(13, 16):
                                    cv2.line(white,
                                             (pts[t][0] + os_x, pts[t][1] + os_y),
                                             (pts[t + 1][0] + os_x, pts[t + 1][1] + os_y),
                                             (0, 255, 0), 3)
                                for t in range(17, 20):
                                    cv2.line(white,
                                             (pts[t][0] + os_x, pts[t][1] + os_y),
                                             (pts[t + 1][0] + os_x, pts[t + 1][1] + os_y),
                                             (0, 255, 0), 3)

                                # Palm connections
                                cv2.line(white, (pts[5][0] + os_x, pts[5][1] + os_y),
                                         (pts[9][0] + os_x, pts[9][1] + os_y), (0, 255, 0), 3)
                                cv2.line(white, (pts[9][0] + os_x, pts[9][1] + os_y),
                                         (pts[13][0] + os_x, pts[13][1] + os_y), (0, 255, 0), 3)
                                cv2.line(white, (pts[13][0] + os_x, pts[13][1] + os_y),
                                         (pts[17][0] + os_x, pts[17][1] + os_y), (0, 255, 0), 3)
                                cv2.line(white, (pts[0][0] + os_x, pts[0][1] + os_y),
                                         (pts[5][0] + os_x, pts[5][1] + os_y), (0, 255, 0), 3)
                                cv2.line(white, (pts[0][0] + os_x, pts[0][1] + os_y),
                                         (pts[17][0] + os_x, pts[17][1] + os_y), (0, 255, 0), 3)
                            except Exception:
                                pass

                            # Draw landmark dots
                            for i in range(21):
                                try:
                                    cv2.circle(white, (pts[i][0] + os_x, pts[i][1] + os_y), 4, (0, 0, 255), -1)
                                except Exception:
                                    pass

                            # paste into 400x400 canvas for visualization
                            skeleton_viz = white

                            # For model input use 400x400
                            model_input = white
                            try:
                                ch1 = self.predict(model_input, pts)
                                pred_label = ch1

                                # Draw predicted label text on camera feed
                                cv2.putText(frame, f"Predicted: {pred_label}", (30, 80),
                                            cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2, cv2.LINE_AA)

                            except Exception as pred_e:
                                print("Prediction error:", pred_e)
                                traceback.print_exc()
                                pass

        # Update GUI widgets
        self.display_image(frame, self.video_label)
        self.display_image(skeleton_viz, self.skeleton_label)

    def display_image(self, img, widget_label):
        if img is None:
            return
        rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb.shape
        bytes_per_line = ch * w
        qt_img = QImage(rgb.data, w, h, bytes_per_line, QImage.Format_RGB888)
        scaled = qt_img.scaled(widget_label.width(), widget_label.height(), Qt.KeepAspectRatio)
        widget_label.setPixmap(QPixmap.fromImage(scaled))

    def closeEvent(self, event):
        try:
            if self.cap:
                self.cap.release()
        except Exception:
            pass
        cv2.destroyAllWindows()
        event.accept()


# -------------------------
# Run app
# -------------------------
if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = SignLanguageApp()
    win.show()
    sys.exit(app.exec_())
