import time
from datetime import timedelta, datetime

import requests
import selenium.common.exceptions
from fake_useragent import UserAgent
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys

import threading
from itertools import islice

import os
import csv

import easyocr
from PIL import Image

import config

client_id = config.client_id
client_secret = config.client_secret

num_threads = config.num_threads
num_pages = config.num_pages

not_stated_message = config.not_stated_message

headers = {
    'User-Agent': UserAgent().random,
}

LOGIN_PAGE = "https://hh.ru/account/login"

token_url = 'https://hh.ru/oauth/token'
token_data = {
    'grant_type': 'client_credentials',
    'client_id': client_id,
    'client_secret': client_secret
}

token_response = requests.post(token_url, data=token_data)
access_token = token_response.json().get('access_token')

vacancies_url = 'https://api.hh.ru/vacancies'
current_datetime = datetime.now()


def get_data(date_from, date_to):
    date_pub_to = current_datetime - timedelta(hours=date_from)
    date_pub_from = current_datetime - timedelta(hours=date_to)

    params = {
        'area': '113',
        'industry': '50',
        'ored_clusters': 'true',
        'date_from': date_pub_from.isoformat(),
        'date_to': date_pub_to.isoformat(),
        'access_token': access_token
    }

    response = requests.get(vacancies_url, params=params)
    vacancies = response.json()

    return vacancies


def process_captcha(image_path):
    reader = easyocr.Reader(['ru'])
    img_data = open(image_path, 'rb').read()
    result = reader.readtext(img_data)
    formatted_text = ' '.join([detection[1] for detection in result[::]]).lower()
    return formatted_text


def process_page(driver, page_range):
    driver = webdriver.Chrome()

    def solve_captcha(text):
        captcha_input = driver.find_element(By.XPATH, '//input[@name="captchaText"]')
        captcha_input.clear()
        captcha_input.send_keys(text)

        time.sleep(2)

        button = WebDriverWait(driver, 2).until(
            EC.presence_of_element_located(
                (By.XPATH, '//button[@data-qa="account-captcha-submit"]'))
        )
        time.sleep(5)
        button.click()

    driver.get(LOGIN_PAGE)

    def login():
        show_more_button = WebDriverWait(driver, 2).until(
            EC.presence_of_element_located(
                (By.XPATH, '//button[@data-qa="expand-login-by-password"]'))
        )
        time.sleep(2)
        show_more_button.click()

        time.sleep(2)

        login_input = driver.find_element(By.XPATH, "//input[@data-qa='login-input-username']")
        login_input.send_keys(config.login)

        password_input = driver.find_element(By.XPATH, "//input[@type='password']")
        password_input.send_keys(config.password)

        password_input.send_keys(Keys.ENTER)

        time.sleep(2)

        current_url = driver.current_url

        is_captcha_showed = "account_login" in str(current_url)

        return is_captcha_showed

    def solve_login_captcha():
        try:
            full_captcha_path = f'full_captcha{str(page_range)[:2]}.png'
            driver.save_screenshot(full_captcha_path)

            im = Image.open(full_captcha_path).convert('L')
            width, height = im.size

            new_width, new_height = 300, 80

            left = (width - new_width) // 2 - 170
            top = (height - new_height) // 2 + 100
            right = (width + new_width) // 2 - 50
            bottom = (height + new_height) // 2 + 150

            im_cropped = im.crop((left, top, right, bottom))
            captcha_path = f'captcha{str(page_range)[:2]}.png'
            im_cropped.save(captcha_path)

            formatted_text = process_captcha(captcha_path)

            solve_captcha(formatted_text)

            time.sleep(5)

            current_url = driver.current_url
            is_captcha_showed = "account_login" in current_url
            return is_captcha_showed
        except Exception:
            return False

    is_login_successful = login()
    if not is_login_successful:
        while not is_login_successful:
            is_login_successful = solve_login_captcha()

    is_captcha_showed = False

    for page_number in page_range:
        links = []
        vacancies = get_data(page_number, page_number + 1)
        for vacancy in vacancies.get('items', []):
            vacancy_url = vacancy.get('alternate_url')
            links.append(vacancy_url)

        for link in links:
            vacancy_req = requests.get(link, headers=headers)
            soup = BeautifulSoup(vacancy_req.content, 'html.parser')

            vacancy_title_element = soup.find('h1', {'class': 'bloko-header-section-1'})
            vacancy_title = vacancy_title_element.text.strip() if vacancy_title_element else not_stated_message

            company_name_element = soup.find('span', class_='vacancy-company-name')
            company_name = company_name_element.get_text(strip=True) if company_name_element else not_stated_message

            description_element = soup.find('div', {'class': 'g-user-content'})
            description_text = description_element.get_text(strip=True)[:50] if description_element else not_stated_message

            city_element = soup.find('p', {'data-qa': 'vacancy-view-location'})
            city = city_element.text.strip() if city_element else None

            date_element = soup.find('p', {'class': 'vacancy-creation-time-redesigned'})
            date = date_element.find('span').text.strip() if date_element else not_stated_message

            address_element = soup.find('div', {'data-qa': 'vacancy-address-with-map'})
            address = address_element.find('span', {
                'data-qa': 'vacancy-view-raw-address'}).text.strip() if address_element else not_stated_message

            if city is None:
                city_element = soup.find('a', {'data-qa': 'vacancy-view-link-location'})
                city = city_element.find('span',
                                         {
                                             'data-qa': 'vacancy-view-raw-address'}).text.strip() if city_element else not_stated_message

            try:

                driver.get(link)

                current_url = driver.current_url

                if "captcha" in str(current_url):
                    is_captcha_showed = True

                while is_captcha_showed is True:
                    full_captcha_path = f'full_captcha_{str(page_range)[:2]}.png'
                    driver.save_screenshot(full_captcha_path)

                    im = Image.open(full_captcha_path).convert('L')
                    width, height = im.size

                    new_width, new_height = 300, 50

                    left = (width - new_width) // 2
                    top_offset = 80
                    top = (height - new_height) // 2 - top_offset
                    right = (width + new_width) // 2
                    bottom = (height + new_height) // 2

                    im_cropped = im.crop((left, top, right, bottom))
                    captcha_path = f'captcha_{str(page_range)[:2]}.png'
                    im_cropped.save(captcha_path)

                    formatted_text = process_captcha(captcha_path)

                    solve_captcha(formatted_text)

                    time.sleep(5)
                    driver.get(link)

                    current_url = driver.current_url

                    if "captcha" not in current_url:
                        is_captcha_showed = False

                try:
                    show_contacts_button = WebDriverWait(driver, 10).until(
                        EC.presence_of_element_located(
                            (By.XPATH, '//button[@data-qa="show-employer-contacts show-employer-contacts_top-button"]'))
                    )
                    time.sleep(2)
                    show_contacts_button.click()
                    time.sleep(2)
                except Exception:
                    email = not_stated_message
                    name = not_stated_message
                    phone = not_stated_message

                time.sleep(2)

                page_source = driver.page_source

                soup = BeautifulSoup(page_source, 'html.parser')

                contacts_block = soup.find('div', class_='vacancy-contacts-call-tracking')

                if contacts_block is not None:

                    try:
                        name = contacts_block.find('div', class_='vacancy-contacts-call-tracking__fio').find(
                            'span').text.strip()
                    except AttributeError:
                        name = not_stated_message

                    try:
                        phone = contacts_block.find('a', class_='bloko-link').text.strip()
                    except AttributeError:
                        phone = not_stated_message

                    try:
                        email = contacts_block.find('a', {'data-qa': 'vacancy-contacts__email'}).text.strip()

                    except AttributeError:
                        email = not_stated_message

                else:
                    contacts_block = soup.find('div', class_='bloko-drop__content')

                    if contacts_block is not None:

                        name_element = contacts_block.find('div', {'data-qa': 'vacancy-contacts__fio'})
                        name = name_element.find('span').text.strip() if name_element else not_stated_message

                        phone_element = contacts_block.find('p', {'data-qa': 'vacancy-contacts__phone'})
                        phone = phone_element.text.strip() if phone_element else not_stated_message

                        email_element = contacts_block.find('a', {'data-qa': 'vacancy-contacts__email'})
                        email = email_element.text.strip() if email_element else not_stated_message

                    else:
                        phone = not_stated_message
                        email = not_stated_message
                        name = not_stated_message
            except selenium.common.exceptions.TimeoutException:
                continue

            if not os.path.isfile('hh.csv'):
                with open('hh.csv', 'w', newline='', encoding='utf-8') as csvfile:
                    header = ['Дата публикации', 'Вакансия', 'Описание', 'Город', 'Компания', 'Контактное лицо',
                              'Телефон', 'E-mail', 'Адрес', 'Ссылка']
                    writer = csv.writer(csvfile)
                    writer.writerow(header)

            with open('hh.csv', 'a', newline='', encoding='utf-8') as csvfile:
                data = [date, vacancy_title, description_text, city, company_name, name,
                        phone, email, address, link]
                writer = csv.writer(csvfile)
                writer.writerow(data)

    driver.quit()


def run_scraping(page_ranges):
    threads = []
    chrome_options = webdriver.ChromeOptions()
    chrome_options.add_argument('--headless')

    drivers = [webdriver.Chrome(options=chrome_options) for _ in range(len(page_ranges))]

    for i, page_range in enumerate(page_ranges):
        thread = threading.Thread(target=process_page, args=(drivers[i], page_range))
        threads.append(thread)
        thread.start()

    for thread in threads:
        thread.join()

    for driver in drivers:
        driver.quit()


def chunked(iterable, n):
    it = iter(iterable)
    return iter(lambda: tuple(islice(it, n)), ())


page_ranges = list(chunked(range(0, num_pages), int(num_pages/num_threads)))

run_scraping(page_ranges)
