import time
from datetime import timedelta, datetime

import requests
import selenium.common.exceptions
from fake_useragent import UserAgent
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support import expected_conditions as EC

from multiprocessing import Lock
import threading
from itertools import islice

import os
import csv

import easyocr
from PIL import Image

import config

browser_count = 0

captcha_lock = Lock()

client_id = config.client_id
client_secret = config.client_secret

num_threads = config.num_threads
num_pages = config.num_pages

hh_login = config.hh_login
hh_password = config.hh_password

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

    # Параметры запроса
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


def process_page(driver, action, page_range, captcha_lock):
    global browser_count

    browser_count += 1

    driver = webdriver.Chrome()
    browser_id = browser_count

    def solve_captcha(text):
        captcha_input = driver.find_element(By.XPATH, '//input[@name="captchaText"]')
        captcha_input.clear()
        captcha_input.send_keys(text)

        time.sleep(10)

        submit_button = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located(
                (By.XPATH, '//button[@data-qa="account-captcha-submit"]'))
        )
        time.sleep(5)
        submit_button.click()
        time.sleep(5)

    def eternal_wait(driver, timeout, condition_type,
                     locator_tuple):
        while True:
            try:
                element = WebDriverWait(driver, timeout).until(
                    condition_type(locator_tuple)
                )
                return element
            except:
                print(f"\n\nWaiting for the element(s) {locator_tuple} to become {condition_type}…")
                time.sleep(0.5)
                continue

    def click_and_wait(element, delay=1):
        action.move_to_element(element).click().perform()
        time.sleep(delay)

    s = 10
    driver.get(LOGIN_PAGE)
    action = ActionChains(driver)
    is_captcha_showed = False

    def login():
        driver.get(LOGIN_PAGE)

        time.sleep(10)

        show_more_button = eternal_wait(driver, s, EC.element_to_be_clickable,
                                        (By.XPATH, '//button[@data-qa="expand-login-by-password"]'))
        time.sleep(10)
        action.click(show_more_button).perform()
        time.sleep(10)

        login_field = eternal_wait(driver, s, EC.element_to_be_clickable,
                                   (By.XPATH, '//input[@data-qa="login-input-username"]'))
        time.sleep(10)
        password_field = eternal_wait(driver, s, EC.element_to_be_clickable, (By.XPATH, '//input[@type="password"]'))
        time.sleep(10)

        login_field.send_keys(hh_login)
        time.sleep(10)
        password_field.send_keys(hh_password)
        time.sleep(10)

        login_button = eternal_wait(driver, s, EC.element_to_be_clickable,
                                    (By.XPATH, "//button[@data-qa='account-login-submit']"))
        click_and_wait(login_button, 5)

    login()

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
                    full_captcha_path = f'full_captcha_{browser_id}.png'
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
                    captcha_path = f'captcha_{browser_id}.png'
                    im_cropped.save(captcha_path)

                    with captcha_lock:
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


def run_scraping(page_ranges, captcha_lock):
    threads = []
    chrome_options = webdriver.ChromeOptions()
    chrome_options.add_argument('--headless')

    drivers = [webdriver.Chrome(options=chrome_options) for _ in range(len(page_ranges))]

    for i, page_range in enumerate(page_ranges):
        action = ActionChains(drivers[i])  # Создание объекта ActionChains для каждого драйвера
        thread = threading.Thread(target=process_page, args=(drivers[i], action, page_range, captcha_lock))
        threads.append(thread)
        thread.start()

    for thread in threads:
        thread.join()

    for driver in drivers:
        driver.quit()


def chunked(iterable, n):
    it = iter(iterable)
    return iter(lambda: tuple(islice(it, n)), ())


page_ranges = list(chunked(range(0, num_pages), (num_pages/num_threads)))

run_scraping(page_ranges, captcha_lock)
