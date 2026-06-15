from daily_check import send_email

def test_email():
    send_email("WH Arrests — test email", "This is a test email from daily_check.py.")
    print("email send attempted")

test_email()