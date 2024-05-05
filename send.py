import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
import time
from colorama import Fore, Style, init
import requests
import math
import random
import re
from itertools import cycle

# Initialize colorama
init(autoreset=True)

class EmailConfig:
    def __init__(self, server, port, email, password, proxy=None):
        self.server = server
        self.port = port
        self.email = email
        self.password = password
        self.proxy = proxy

class EmailSender:
    def __init__(self, total_emails):
        self.total_emails = total_emails
        self.sent_emails = 0
        self.failed_emails = []
        self.sent_lock = threading.Lock()
        self.stop_execution = False
        self.start_time = time.time()

    def send_email(self, smtp_server, smtp_port, sender_email, sender_password, recipient_email, subject, body, sender_name, proxy=None):
        try:
            message = MIMEMultipart()
            message['From'] = f'{sender_name} <{sender_email}>'
            message['To'] = recipient_email
            message['Subject'] = subject
            message.attach(MIMEText(body, 'html'))
            
            if proxy:
                proxies = {"http": f"http://{proxy}", "https": f"http://{proxy}"}
                session = requests.Session()
                session.proxies.update(proxies)
                session.post(f"http://{smtp_server}:{smtp_port}")

            with smtplib.SMTP(smtp_server, smtp_port) as server:
                if proxy:
                    server.connect(proxy.split(':')[0], int(proxy.split(':')[1]))
                    server.sock = server._create_socket_proxy()
                    server.sock.connect((smtp_server, smtp_port))
                    server.ehlo()

                server.starttls()
                server.login(sender_email, sender_password)
                server.sendmail(sender_email, recipient_email, message.as_string())

            with self.sent_lock:
                self.sent_emails += 1

            print(Fore.GREEN + f"Email sent successfully to {recipient_email} using {sender_email} with subject: {subject}." +
                  f" Total time: {self.get_elapsed_time():.2f} seconds. Total emails sent: {self.sent_emails}" +
                  f" (SMTP Total Sent: {self.sent_emails}/{self.total_emails})" + Style.RESET_ALL)

        except Exception as e:
            print(f"Error sending email to {recipient_email}: {e}")
            self.failed_emails.append(recipient_email)

        if self.sent_emails >= self.total_emails:
            self.stop_execution = True

    def should_stop_execution(self):
        return self.stop_execution

    def get_elapsed_time(self):
        return time.time() - self.start_time

def read_configurations_from_file(file_path):
    configurations = []
    with open(file_path, 'r') as file:
        for line in file:
            parts = line.strip().split()
            config = EmailConfig(parts[0], int(parts[1]), parts[2], parts[3])
            if len(parts) == 5:
                config.proxy = parts[4]
            configurations.append(config)
    return configurations

def read_recipients_from_file(file_path):
    recipients = []
    with open(file_path, 'r') as file:
        for line in file:
            recipient = line.strip()
            if recipient:
                recipients.append(recipient)
    return recipients

def read_email_content(file_path):
    with open(file_path, 'r', encoding='utf-8') as file:
        content = file.readlines()
    
    sender_name = subject = body = None
    for line in content:
        if line.startswith("from:"):
            sender_name = line.split("from:")[1].strip()
        elif line.startswith("subject:"):
            subject = line.split("subject:")[1].strip()
        elif line.startswith("body:"):
            body = line.split("body:")[1].strip()
    
    if not (sender_name and subject and body):
        raise ValueError("Sender's name, subject, and body must be provided in email_content.txt")
    
    return sender_name, subject, body

def read_placeholder_from_file(file_path):
    placeholders = []
    with open(file_path, 'r') as placeholder_file:
        for line in placeholder_file:
            placeholders.append(line.strip())
    return cycle(placeholders)

def send_emails_for_config(email_sender, configurations, recipient_emails, sender_name, email_subject, email_body, delay_time, num_connections, placeholder_files, max_retries=3):
    while not email_sender.should_stop_execution() and max_retries > 0:
        email_sender.failed_emails = []  # Reset failed emails list
        with ThreadPoolExecutor(max_workers=num_connections) as executor:
            futures = []

            batch_size = 100
            num_batches = math.ceil(len(recipient_emails) / batch_size)
            placeholder_cycles = [read_placeholder_from_file(os.path.join('placeholders', file_name)) for file_name in placeholder_files]

            for batch_num in range(num_batches):
                start_idx = batch_num * batch_size
                end_idx = min((batch_num + 1) * batch_size, len(recipient_emails))
                batch_recipients = recipient_emails[start_idx:end_idx]

                if batch_num % num_connections == 0 and batch_num != 0:
                    if delay_time:
                        delay = delay_time
                    else:
                        delay = 0  # Default no delay if not specified by user
                    time.sleep(delay)  # Introduce delay between batches of connections

                for recipient_email in batch_recipients:
                    config = random.choice(configurations)  # Select a random SMTP configuration

                    # Replace placeholders with actual values for each recipient
                    personalized_email_content = email_body
                    for i, placeholder_cycle in enumerate(placeholder_cycles):
                        tag = f'[placeholder{i + 1}]'
                        personalized_email_content = personalized_email_content.replace(tag, next(placeholder_cycle))

                    future = executor.submit(
                        email_sender.send_email,
                        config.server, config.port, config.email, config.password,
                        recipient_email, email_subject, personalized_email_content, sender_name, config.proxy
                    )

                    futures.append(future)

            for future in as_completed(futures):
                try:
                    future.result()
                except Exception as e:
                    print(f"Error: {e}")

        # Retry sending emails to failed recipients
        recipient_emails = email_sender.failed_emails
        max_retries -= 1

    if email_sender.sent_emails < email_sender.total_emails:
        print(Fore.RED + "Failed to send emails to all recipients." + Style.RESET_ALL)
        # Resend emails to remaining recipients
        while recipient_emails:
            email_sender.failed_emails = []  # Reset failed emails list
            send_emails_for_config(email_sender, configurations, recipient_emails, sender_name, email_subject, email_body, delay_time, num_connections, placeholder_files, max_retries=1)
            if email_sender.sent_emails == email_sender.total_emails:
                break

if __name__ == "__main__":
    configurations_file = "configurations_orange.txt"
    recipients_file = "recipients.txt"
    email_content_file = "emails_content.txt"
    placeholders_folder = "placeholders"

    smtp_configs = read_configurations_from_file(configurations_file)
    recipient_emails = read_recipients_from_file(recipients_file)
    sender_name, email_subject, email_body = read_email_content(email_content_file)
    placeholder_files = os.listdir(placeholders_folder)

    total_emails = len(recipient_emails)

    # Set default values for delay time and number of connections
    delay_time = None  # Set to None for no delay, or specify a value in seconds
    num_connections = 100  # Default number of concurrent connections

    try:
        print(f"Sending emails with subject: {email_subject}...")

        email_sender = EmailSender(total_emails)
        send_emails_for_config(email_sender, smtp_configs, recipient_emails, sender_name, email_subject, email_body, delay_time, num_connections, placeholder_files)

        elapsed_time = email_sender.get_elapsed_time()
        total_sent_emails = email_sender.sent_emails

        print(Fore.GREEN + f"All emails sent. Total time: {elapsed_time:.2f} seconds. Total emails sent: {total_sent_emails}" + Style.RESET_ALL)

    except Exception as e:
        print(f"An unexpected error occurred: {e}")
    finally:
        print("Stopping further execution.")
