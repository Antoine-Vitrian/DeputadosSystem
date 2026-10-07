from django.db import models


class LegislativeLevel(models.TextChoices):
    FEDERAL = "FEDERAL", "Câmara dos Deputados"
    STATE = "STATE", "ALESP"
    MUNICIPAL = "MUNICIPAL", "Câmara Municipal de São Paulo"


class DataSource(models.Model):
    name = models.CharField(max_length=160)
    url = models.URLField()
    identifier = models.CharField(max_length=120, blank=True)
    last_synced_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return self.name


class Party(models.Model):
    name = models.CharField(max_length=160)
    acronym = models.CharField(max_length=30, blank=True)
    external_id = models.CharField(max_length=80, null=True, blank=True, unique=True)

    def __str__(self):
        return self.acronym or self.name


class Parliamentarian(models.Model):
    external_id = models.CharField(max_length=80, unique=True)
    name = models.CharField(max_length=180)
    civil_name = models.CharField(max_length=180, blank=True)
    photo_url = models.URLField(blank=True)
    role = models.CharField(max_length=120, blank=True)
    state = models.CharField(max_length=2, blank=True)
    city = models.CharField(max_length=120, blank=True)
    level = models.CharField(max_length=20, choices=LegislativeLevel.choices)
    party = models.ForeignKey(Party, null=True, blank=True, on_delete=models.SET_NULL, related_name="parliamentarians")
    source = models.ForeignKey(DataSource, null=True, blank=True, on_delete=models.SET_NULL)
    is_mock = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        indexes = [
            models.Index(fields=["level", "name"]),
            models.Index(fields=["level", "state"]),
            models.Index(fields=["level", "is_active", "name"]),
        ]

    def __str__(self):
        return self.name


class Mandate(models.Model):
    parliamentarian = models.ForeignKey(Parliamentarian, on_delete=models.CASCADE, related_name="mandates")
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    description = models.CharField(max_length=180, blank=True)


class Theme(models.Model):
    name = models.CharField(max_length=120, unique=True)

    def __str__(self):
        return self.name


class Project(models.Model):
    class Status(models.TextChoices):
        IN_PROGRESS = "IN_PROGRESS", "Em tramitação"
        APPROVED = "APPROVED", "Aprovado"
        REJECTED = "REJECTED", "Rejeitado"
        ARCHIVED = "ARCHIVED", "Arquivado"

    external_id = models.CharField(max_length=100, unique=True)
    code = models.CharField(max_length=100)
    title = models.CharField(max_length=300)
    description = models.TextField(blank=True)
    type_description = models.CharField(max_length=120, blank=True)
    keywords = models.TextField(blank=True)
    situation = models.CharField(max_length=240, blank=True)
    regime = models.CharField(max_length=160, blank=True)
    full_text_url = models.URLField(blank=True)
    text_summary = models.TextField(blank=True)
    presented_at = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.IN_PROGRESS)
    level = models.CharField(max_length=20, choices=LegislativeLevel.choices)
    author = models.ForeignKey(Parliamentarian, null=True, blank=True, on_delete=models.SET_NULL, related_name="projects")
    themes = models.ManyToManyField(Theme, blank=True, related_name="projects")
    source = models.ForeignKey(DataSource, null=True, blank=True, on_delete=models.SET_NULL)
    is_mock = models.BooleanField(default=False)

    class Meta:
        ordering = ["-presented_at", "-id"]
        indexes = [
            models.Index(fields=["level", "-presented_at"]),
            models.Index(fields=["status", "-presented_at"]),
        ]

    def __str__(self):
        return f"{self.code} - {self.title}"


class Expense(models.Model):
    parliamentarian = models.ForeignKey(Parliamentarian, on_delete=models.CASCADE, related_name="expenses")
    external_id = models.CharField(max_length=120, unique=True)
    year = models.PositiveSmallIntegerField()
    month = models.PositiveSmallIntegerField(null=True, blank=True)
    category = models.CharField(max_length=240, blank=True)
    supplier = models.CharField(max_length=240, blank=True)
    document_number = models.CharField(max_length=120, blank=True)
    value = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    document_url = models.URLField(blank=True)
    source = models.ForeignKey(DataSource, null=True, blank=True, on_delete=models.SET_NULL)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-year", "-month", "-value"]


class Committee(models.Model):
    name = models.CharField(max_length=180)
    level = models.CharField(max_length=20, choices=LegislativeLevel.choices)
    projects = models.ManyToManyField(Project, blank=True, related_name="committees")


class Voting(models.Model):
    external_id = models.CharField(max_length=100, unique=True)
    project = models.ForeignKey(Project, null=True, blank=True, on_delete=models.SET_NULL, related_name="votings")
    title = models.CharField(max_length=300)
    description = models.TextField(blank=True)
    organ = models.CharField(max_length=60, blank=True)
    procedure = models.CharField(max_length=240, blank=True)
    subject_detail = models.TextField(blank=True)
    voted_at = models.DateTimeField()
    result = models.CharField(max_length=120, blank=True)
    level = models.CharField(max_length=20, choices=LegislativeLevel.choices)
    source = models.ForeignKey(DataSource, null=True, blank=True, on_delete=models.SET_NULL)
    official_url = models.URLField(blank=True)

    class Meta:
        ordering = ["-voted_at", "-id"]
        indexes = [models.Index(fields=["level", "-voted_at"])]


class Vote(models.Model):
    class Choice(models.TextChoices):
        YES = "YES", "Sim"
        NO = "NO", "Não"
        ABSTENTION = "ABSTENTION", "Abstenção"
        ABSENT = "ABSENT", "Ausente"

    voting = models.ForeignKey(Voting, on_delete=models.CASCADE, related_name="votes")
    parliamentarian = models.ForeignKey(Parliamentarian, on_delete=models.CASCADE, related_name="votes")
    choice = models.CharField(max_length=20, choices=Choice.choices)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["voting", "parliamentarian"], name="unique_vote_per_parliamentarian")]


class ProcessingEvent(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="processing_events")
    occurred_at = models.DateTimeField()
    description = models.CharField(max_length=300)
    source = models.ForeignKey(DataSource, null=True, blank=True, on_delete=models.SET_NULL)


class NewsArticle(models.Model):
    class Category(models.TextChoices):
        POLITICS = "POLITICS", "Política"
        CONGRESS = "CONGRESS", "Congresso"
        GOVERNMENT = "GOVERNMENT", "Governo"
        STF = "STF", "STF"
        ELECTIONS = "ELECTIONS", "Eleições"
        ECONOMY = "ECONOMY", "Economia"
        SAO_PAULO = "SAO_PAULO", "São Paulo"

    title = models.CharField(max_length=300)
    url = models.URLField(unique=True)
    summary = models.TextField(blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    category = models.CharField(max_length=30, choices=Category.choices)
    source = models.ForeignKey(DataSource, null=True, blank=True, on_delete=models.SET_NULL)
    parliamentarians = models.ManyToManyField(Parliamentarian, blank=True)
    projects = models.ManyToManyField(Project, blank=True)

    class Meta:
        ordering = ["-published_at", "-id"]
        indexes = [models.Index(fields=["category", "-published_at"])]


class DailyBrief(models.Model):
    reference_date = models.DateField(unique=True)
    summary = models.TextField()
    article_count = models.PositiveSmallIntegerField(default=0)
    generated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-reference_date"]

    def __str__(self):
        return f"Resumo político de {self.reference_date:%d/%m/%Y}"


class Notification(models.Model):
    parliamentarian = models.ForeignKey(Parliamentarian, null=True, blank=True, on_delete=models.CASCADE)
    project = models.ForeignKey(Project, null=True, blank=True, on_delete=models.CASCADE)
    voting = models.ForeignKey(Voting, null=True, blank=True, on_delete=models.CASCADE)
    message = models.CharField(max_length=300)
    created_at = models.DateTimeField(auto_now_add=True)
    is_read = models.BooleanField(default=False)
