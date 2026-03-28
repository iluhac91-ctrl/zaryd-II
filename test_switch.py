import time
import RPi.GPIO as GPIO

SWITCH_PIN = 5  # BCM 5

GPIO.setwarnings(False)
GPIO.setmode(GPIO.BCM)
GPIO.setup(SWITCH_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)

print("Тест микрика запущен.")
print("Нажимай и отпускай рычаг. Для выхода Ctrl+C.")

try:
    last_state = None

    while True:
        state = GPIO.input(SWITCH_PIN)

        if state != last_state:
            if state == GPIO.LOW:
                print("LOW  -> контакт замкнут / датчик нажат")
            else:
                print("HIGH -> контакт разомкнут / датчик отпущен")
            last_state = state

        time.sleep(0.05)

except KeyboardInterrupt:
    print("Остановка теста.")

finally:
    GPIO.cleanup()
