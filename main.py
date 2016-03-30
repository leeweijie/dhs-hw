#!/usr/bin/env python
#
# Copyright 2007 Google Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
import os
import cgi
import webapp2
import jinja2
import datetime
import json
import string

from google.appengine.ext import ndb
from google.appengine.api import users
from googleapiclient.discovery import build
from oauth2client.appengine import OAuth2DecoratorFromClientSecrets

decorator = OAuth2DecoratorFromClientSecrets(
    os.path.join(os.path.dirname(__file__), 'client_secret.json'),
    scope=['https://www.googleapis.com/auth/plus.me','email'],
    hd='dhs.sg')

service = build("plus", "v1")

jhsubjects = ['Others', 'Art', 'Biology', 'Chemistry', 'Computing', 'Chinese', 'C Lit', 'Economics', 'E Lit', 'Geography', 'History', 'LA / GP', 'Math', 'Music', 'Physics']
shsubjects = jhsubjects+['CLL', 'ELL']


JINJA_ENVIRONMENT = jinja2.Environment(
    loader=jinja2.FileSystemLoader(os.path.dirname(__file__)),
    extensions=['jinja2.ext.autoescape'],
    autoescape=True)

def task_key(user_class):
    return ndb.Key('datastore', user_class)

def check_task_expired(task):
    if task.due_date and task.due_date<datetime.date.today():
        try:
            task.key.delete()
            return True
        except:
            pass
    return False

def dhs_domain_check(func):
    def func_wrapper(self):    
        email = users.get_current_user().email()
        me_person = service.people().get(userId='me').execute(decorator.http())
        oauth_email = me_person['emails'][0]['value']
        if email == oauth_email:
            domain = me_person['domain']
            if domain == 'dhs.sg':
                return func(self)
            else:
                return domain_error_handler(self)
        else:
            decorator.get_credentials().revoke(decorator.http())
            self.redirect(users.create_logout_url('/profile'))

    return func_wrapper

def domain_error_handler(self):
    logout_url = users.create_logout_url('/profile')
    template = JINJA_ENVIRONMENT.get_template('html/domain_error.html')
    self.response.write(template.render({'logout_url': logout_url}))

def subject_combi_check(func):
    def func_wrapper(self):
        subjects_query = SubjectCombi.query(ancestor=ndb.Key('email', users.get_current_user().email()))
        subjects = subjects_query.fetch()
        if subjects:
            return func(self, subjects[0].combi)
        else:
            return choose_subject_combi(self)
    return func_wrapper

def choose_subject_combi(self, subjects=[]):
    template = JINJA_ENVIRONMENT.get_template('html/choose_subjects.html')
    self.response.write(template.render({'subjects': shsubjects, 'selected':subjects}))

class Author(ndb.Model):
    name = ndb.StringProperty(indexed=False)
    email = ndb.StringProperty(indexed=True)

class UserData(ndb.Model):
    email = ndb.StringProperty(indexed=True)
    task_done = ndb.BooleanProperty(indexed=False)

class SubjectCombi(ndb.Model):
    combi = ndb.PickleProperty()

class Task(ndb.Model):
    author = ndb.StructuredProperty(Author)
    name = ndb.StringProperty(indexed=False, required=True)
    subject = ndb.StringProperty(indexed=True, required=True, choices = shsubjects)
    private = ndb.BooleanProperty(indexed=True, required=True)
    priority = ndb.IntegerProperty(indexed=True, choices=range(1,4))
    description = ndb.StringProperty(indexed=False)
    time_created = ndb.DateTimeProperty(auto_now_add=True)
    due_date = ndb.DateProperty(auto_now_add=False)
    time_needed = ndb.IntegerProperty(indexed=False, choices = range(1, 11))

    urlid = ''
    date_created_f = ''
    due_date_f = ''
    due_soon = False

def task_query(user_class, subjects, sort_member=Task.time_created, reverse=False):
    if reverse:
        tasks_query = Task.query(Task.subject.IN(subjects), ndb.OR(Task.private==False, Task.author.email==users.get_current_user().email()), ancestor=task_key(user_class)).order(-sort_member)
    else:
        tasks_query = Task.query(Task.subject.IN(subjects), ndb.OR(Task.private==False, Task.author.email==users.get_current_user().email()), ancestor=task_key(user_class)).order(sort_member)
    return tasks_query.fetch()

def user_data_query(task_key):
    user_data_query = UserData.query(UserData.email==users.get_current_user().email(),ancestor=task_key)
    return (user_data_query.fetch(1))

class MainPage(webapp2.RequestHandler):
    def get(self):
        template = JINJA_ENVIRONMENT.get_template('html/landing.html')
        self.response.write(template.render({}))

class Profile(webapp2.RequestHandler):
    @decorator.oauth_required
    @dhs_domain_check
    @subject_combi_check
    def get(self, subjects):
        http = decorator.http()
        mePerson = service.people().get(userId='me').execute(http=http)
        display_name = str(mePerson['displayName'])
        user_image_url = str(mePerson['image']['url'])
        user_class = display_name.split()[0][3:]
        name = ' '.join(display_name.split()[1:])
        signout_url = users.create_logout_url(dest_url='/')
        template = JINJA_ENVIRONMENT.get_template('html/profile.html')
        self.response.write(template.render({'name':name, 'class':user_class, 'user_image':user_image_url, 'signout_url':signout_url}))

class Dashboard(webapp2.RequestHandler):
    @decorator.oauth_required
    @dhs_domain_check
    @subject_combi_check
    def get(self, subjects):
        http = decorator.http()
        mePerson = service.people().get(userId='me').execute(http=http)
        display_name = str(mePerson['displayName'])
        user_class = display_name.split()[0][3:]
        
        sort_type = str(self.request.get('sort'))
        if sort_type=='due_date':
            tasks = task_query(user_class, subjects, sort_member=Task.due_date)
        elif sort_type=='subject':
            tasks = task_query(user_class, subjects, sort_member=Task.subject)
        elif sort_type=='priority':
            tasks = task_query(user_class, subjects, sort_member=Task.priority, reverse=True)
        else:
            tasks = task_query(user_class, subjects, reverse=True)
        
        items_deleted = False
        
        for task in tasks:
            if check_task_expired(task):
                items_deleted = True

        if items_deleted:
            if sort_type=='due_date':
                tasks = task_query(user_class, subjects, sort_member=Task.due_date)
            elif sort_type=='subject':
                tasks = task_query(user_class, subjects, sort_member=Task.subject)
            elif sort_type=='priority':
                tasks = task_query(user_class, subjects, sort_member=Task.priority, reverse=True)
            else:
                tasks = task_query(user_class, subjects, reverse=True)

        for task in tasks:
            task.urlid = task.key.urlsafe()

        for task in tasks:
            task.time_created_f = '-'.join(reversed(str(task.time_created.date()).split('-')))
            if task.due_date:
                task.due_date_f = '-'.join(reversed(str(task.due_date).split('-')))
                if task.due_date-datetime.date.today()<datetime.timedelta(days=2):
                    task.due_soon = True
        
        if sort_type=='due_date':
            tasks = [task for task in tasks if task.due_date] + sorted([task for task in tasks if not task.due_date], reverse=True, key=lambda x:x.time_created)
        elif sort_type=='subject':
            tasks = [task for task in tasks if task.subject != 'Others'] + sorted([task for task in tasks if task.subject=='Others'], reverse=True, key=lambda x:x.time_created)
        #elif sort_type=='priority':
            # tasks = [task for task in tasks if task.priority] + sorted([task for task in tasks if not task.priority], reverse=True, key=lambda x:x.time_created)

        tab_done = self.request.get('tab')=='done'

        if tab_done:
            tasks = [task for task in tasks if user_data_query(task.key) and user_data_query(task.key)[0].task_done]
        else:
            tasks = [task for task in tasks if not user_data_query(task.key) or not user_data_query(task.key)[0].task_done]

        template = JINJA_ENVIRONMENT.get_template('html/dashboard.html')
        url = self.request.url
        if not(self.request.get('tab') and self.request.get('sort')):
            url+='?tab=undone&sort=time_created'
            sort_type = 'time_created'

        urls = {}
        possible_sorts = ['time_created', 'due_date', 'subject', 'priority']
        possible_sorts.remove(sort_type)
        for p in possible_sorts:
            urls[p] = string.replace(url, sort_type, p)
        
        if tab_done:
            urls['tab'] = string.replace(url, 'done', 'undone')
        else:
            urls['tab'] = string.replace(url, 'undone', 'done')

        self.response.write(template.render({'tasks':tasks, 'class':user_class, 'sort_type':sort_type, 'urls':urls, 'tab_done':tab_done}))

class Addtask(webapp2.RequestHandler):
    @decorator.oauth_required
    @dhs_domain_check
    @subject_combi_check
    def get(self, subjects):
        min_date = str(datetime.date.today()+datetime.timedelta(days=1))
        template = JINJA_ENVIRONMENT.get_template('html/addtask.html')
        self.response.write(template.render({'min_date':min_date, 'subjects':subjects}))

class Viewtask(webapp2.RequestHandler):
    @decorator.oauth_required
    @dhs_domain_check
    @subject_combi_check
    def get(self, subjects):
        task_id = self.request.get('id')
        task = ndb.Key(urlsafe=task_id).get()
        if not check_task_expired(task):
            task.urlid = task_id
            task.time_created_f = '-'.join(reversed(str(task.time_created.date()).split('-')))
            if task.due_date:
                task.due_date_f = '-'.join(reversed(str(task.due_date).split('-')))

            owntask = (task.author.email==users.get_current_user().email())
            task_done = user_data_query(task.key)
            if task_done:
                task_done=task_done[0].task_done
            else:
                task_done=False
            template = JINJA_ENVIRONMENT.get_template('html/viewtask.html')
            self.response.write(template.render({'task': task, 'owntask': owntask, 'task_done':task_done}))
        else:
            self.redirect('/dashboard')

class Deletetask(webapp2.RequestHandler):
    @decorator.oauth_required
    @dhs_domain_check
    @subject_combi_check
    def get(self, subjects): 
        task_id = self.request.get('id')
        task = ndb.Key(urlsafe=task_id).get()
        if task.author.email==users.get_current_user().email():
            try:
                task.key.delete()
            except:
                pass
        self.redirect('/dashboard')

class Submit(webapp2.RequestHandler):
    @decorator.oauth_required
    @dhs_domain_check
    @subject_combi_check
    def post(self, subjects):
        if self.request.get('name'):
            http = decorator.http()
            mePerson = service.people().get(userId='me').execute(http=http)
            display_name = str(mePerson['displayName'])
            name = ' '.join(display_name.split()[1:])
            user_class = display_name.split()[0][3:]
            email = str(users.get_current_user().email())
            priority = int(self.request.get('priority'))

            task = Task(parent=task_key(user_class))
            task.name = self.request.get('name')
            task.author = Author(name=name, email = email)
            task.subject = self.request.get('subject')
            task.private = str(self.request.get('type'))=='private'
            due_date = self.request.get('due_date')
            description = self.request.get('description')
            time_needed = int(self.request.get('time_needed'))
            if description:
                task.description = description
            if due_date:
                task.due_date = datetime.datetime.strptime(due_date, '%Y-%m-%d').date()
            if time_needed != 0:
                task.time_needed = time_needed
            if priority != 0:
                task.priority = priority
            task.put()
        self.redirect('/dashboard')

class Edittask(webapp2.RequestHandler):
    @decorator.oauth_required
    @dhs_domain_check
    @subject_combi_check
    def get(self, subjects): 
        task_id = self.request.get('id')
        task = ndb.Key(urlsafe=task_id).get()
        min_date = datetime.date.today()+datetime.timedelta(days=1)
        template = JINJA_ENVIRONMENT.get_template('html/edittask.html')
        self.response.write(template.render({'task': task, 'subjects':subjects, 'min_date':min_date, 'id':task_id}))

class Update(webapp2.RequestHandler):
    @decorator.oauth_required
    @dhs_domain_check
    @subject_combi_check
    def post(self, subjects):
        task = ndb.Key(urlsafe=self.request.get('id')).get()
        if self.request.get('name') and task.author.email==users.get_current_user().email():
            task.name = self.request.get('name')
            task.time_created = datetime.datetime.now()
            task.private = str(self.request.get('type'))=='private'
            task.description = self.request.get('description')
            due_date = self.request.get('due_date')
            time_needed = int(self.request.get('time_needed'))
            priority = int(self.request.get('priority'))

            if due_date:
                task.due_date = datetime.datetime.strptime(due_date, '%Y-%m-%d').date()
            else:
                task.due_date = None
            if time_needed != 0:
                task.time_needed = time_needed
            else:
                task.time_needed = None

            if priority != 0:
                task.priority = priority

            task.put()
        try:
            self.redirect('/viewtask?id='+self.request.get('id'))
        except:
            self.redirect('/dashboard')

class ToggleDone(webapp2.RequestHandler):
    @decorator.oauth_required
    @dhs_domain_check
    @subject_combi_check
    def get(self, subjects):
        task_key = ndb.Key(urlsafe=self.request.get('id'))
        user_data = user_data_query(task_key)
        if user_data:
            user_data = user_data[0]
            user_data.task_done = not user_data.task_done
            user_data.put()
        else:
            user_data = UserData(parent=task_key)
            user_data.email = users.get_current_user().email()
            user_data.task_done = True
            user_data.put()
        self.redirect('/viewtask?id='+self.request.get('id'))

class AddSubjectCombi(webapp2.RequestHandler):
    @decorator.oauth_required
    @dhs_domain_check
    def post(self):
        subjects = self.request.get_all('subjects')
        verified = True
        subjects = [str(s) for s in subjects]
        for subject in subjects:
            if subject not in shsubjects:
                verified = False
        if verified:
            subjects_query = SubjectCombi.query(ancestor=ndb.Key('email', users.get_current_user().email()))
            subject_combi = subjects_query.fetch()
            
            if subject_combi:
                subject_combi = subject_combi[0]
                subject_combi.combi=['Others']+subjects
                subject_combi.put()
            else:
                subject_combi = SubjectCombi(parent=ndb.Key('email', users.get_current_user().email()))
                subject_combi.combi = ['Others']+subjects
                subject_combi.put()
        self.redirect('/profile')

class EditSubject(webapp2.RequestHandler):
    @decorator.oauth_required
    @dhs_domain_check
    @subject_combi_check
    def get(self, subjects):
        choose_subject_combi(self, subjects)
    
app = webapp2.WSGIApplication([
    ('/', MainPage),
    (decorator.callback_path, decorator.callback_handler()),
    ('/dashboard', Dashboard),
    ('/addtask', Addtask),
    ('/submit', Submit),
    ('/viewtask', Viewtask),
    ('/deletetask', Deletetask),
    ('/edittask', Edittask),
    ('/update', Update),
    ('/done', ToggleDone),
    ('/add_subject', AddSubjectCombi),
    ('/edit_subject', EditSubject),
    ('/profile', Profile)],
    debug=True)
