from django.contrib import admin
from .models import DailyBrief, DataSource, NewsArticle, Parliamentarian, Party, Project, Theme, Voting, Vote

admin.site.register([DailyBrief, DataSource, NewsArticle, Parliamentarian, Party, Project, Theme, Voting, Vote])
