import json
import logging
import uuid

from django.db import models
from django.utils import timezone
from django.utils.text import slugify
from django.conf import settings
from channels import Group
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth.models import User

import radio.choices as choice

log = logging.getLogger(__name__)

class Agency(models.Model):
    name = models.CharField(max_length=100)
    short = models.CharField(max_length=5, unique=True)

    def __str__(self):
        return self.name

    def get_short(self):
        return self.short


class Source(models.Model):
    description = models.CharField(max_length=100)

    class Meta:
        ordering = ["pk"]

    def __str__(self):
        return self.description

class Unit(models.Model):
    dec_id = models.IntegerField(unique=True)
    description = models.CharField(max_length=100, blank=True, null=True)
    agency = models.ForeignKey(Agency, default=settings.RADIO_DEFAULT_UNIT_AGENCY)
    #agency = models.ForeignKey(Agency, default=2)
    type = models.CharField(max_length=1, choices=choice.RADIO_TYPE_CHOICES, default=choice.RADIO_TYPE_MOBILE)
    number = models.IntegerField(default=1)

    def __str__(self):
        if(self.description):
            return self.description
        else:
            return str(self.dec_id)

class TalkGroup(models.Model):
    dec_id = models.IntegerField(unique=True)
    alpha_tag = models.CharField(max_length=30)
    common_name = models.CharField(max_length=10, blank=True, null=True)
    description = models.CharField(max_length=100, blank=True, null=True)
    slug = models.SlugField(null=True)
    public = models.BooleanField(default=True)
    comments = models.CharField(max_length=100, blank=True, null=True)

    class Meta:
        ordering = ["alpha_tag"]

    def __str__(self):
        return self.alpha_tag

    def save(self, *args, **kwargs):
        self.slug = slugify(self.alpha_tag)
        super(TalkGroup, self).save(*args, **kwargs)

class Transmission(models.Model):
    slug = models.UUIDField(db_index=True, default=uuid.uuid4, editable=False) 
    start_datetime = models.DateTimeField(db_index=True)
    audio_file = models.FileField()
    talkgroup = models.IntegerField()
    talkgroup_info = models.ForeignKey(TalkGroup)
    freq = models.IntegerField()
    emergency = models.BooleanField(default=False)
    units = models.ManyToManyField(Unit, through='TranmissionUnit')
    play_length = models.FloatField(default=0.0)
    source = models.ForeignKey(Source, default=0)

    def __str__(self):
        return '{} {}'.format(self.talkgroup, self.start_datetime)

    @property
    def local_start_datetime(self):
        return timezone.localtime(self.start_datetime).strftime('%H:%M:%S %m/%d/%Y')

    def as_dict(self):
        return {'start_datetime': str(self.start_datetime), 'audio_file': str(self.audio_file), 'talkgroup_desc': self.talkgroup_info.alpha_tag}

    def print_play_length(self):
        m, s = divmod(int(self.play_length), 60)
        return '{:02d}:{:02d}'.format(m,s)

    def freq_mhz(self):
        return '{0:07.3f}'.format(self.freq / 1000000)

    def tg_name(self):
        """Returns TalkGroup name used for page title
           First tries TalkGroup.common_name
           then TalkGroup.alpha_tag
        """
        if self.talkgroup_info.common_name:
            return self.talkgroup_info.common_name
        else:
            return self.talkgroup_info.alpha_tag

    class Meta:
        ordering = ["-pk"]


@receiver(post_save, sender=Transmission, dispatch_uid="send_mesg")
def send_mesg(sender, instance, **kwargs):
    #log.debug('Hit post save()')
    #log.debug('DATA %s', json.dumps(instance.as_dict()))
    log.debug('DATA %s', json.dumps(instance.as_dict()))
    tg = TalkGroup.objects.get(pk=instance.talkgroup_info.pk)
    groups = tg.scanlist_set.all()
    for g in groups:
        Group('livecall-scan-'+g.name, ).send({'text': json.dumps(instance.as_dict())})
    Group('livecall-tg-' + tg.slug, ).send({'text': json.dumps(instance.as_dict())})


    #def save(self, *args, **kwargs):
    #    try:
    #        self.talkgroup_info = TalkGroup.objects.get(dec_id=self.talkgroup)
    #    except TalkGroup.DoesNotExist:
    #        new_tg = TalkGroup(dec_id=self.talkgroup, alpha_tag='UNK')
    #        new_tg.save
    #        self.talkgroup_info = TalkGroup.objects.get(dec_id=self.talkgroup)
    #    super(Transmission, self).save(*args, **kwargs)

class TranmissionUnit(models.Model):
    transmission = models.ForeignKey(Transmission, on_delete=models.CASCADE)
    unit = models.ForeignKey(Unit, on_delete=models.CASCADE)
    order = models.IntegerField()

    class Meta:
        ordering = ["order"]

    def __str__(self):
        return '{} on {}'.format(self.unit,self.transmission)

class ScanList(models.Model):
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL)
    public = models.BooleanField(default=False)
    name = models.CharField(max_length=30, unique=True)
    description = models.CharField(max_length=100)
    talkgroups = models.ManyToManyField(TalkGroup)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return '{}'.format(self.name)

class MenuList(models.Model):
    order = models.IntegerField(default=1)

    class Meta:
        abstract = True
        ordering = ["order", "name"]

    def __str__(self):
        return '{}'.format(self.name)

    @property
    def scan_name(self):
        return self.name

    @property
    def scan_description(self):
        return self.name.description

class MenuScanList(MenuList):
    name = models.ForeignKey(ScanList)

    @property
    def scan_name(self):
        return self.name.name

    @property
    def scan_description(self):
        return self.name.description


class MenuTalkGroupList(MenuList):
    name = models.ForeignKey(TalkGroup)

    @property
    def tg_name(self):
        return self.name.alpha_tag

    @property
    def tg_slug(self):
        return self.name.slug


class Plan(models.Model):
    DEFAULT_PK = 1 # This is added via a migration
    name = models.CharField(max_length=30, unique=True)

    def __str__(self):
        return '{}'.format(self.name)


class Profile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    plan = models.ForeignKey(Plan, default=Plan.DEFAULT_PK)


def create_profile(sender, **kwargs):
    user = kwargs["instance"]
    if kwargs["created"]:
        default_plan = Plan.objects.get(pk=Plan.DEFAULT_PK)
        up = Profile(user=user, plan=default_plan)
        up.save()


post_save.connect(create_profile, sender=User)

