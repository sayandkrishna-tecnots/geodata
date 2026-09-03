"""Models for the geodata reference tables.

Three design points, all forced by the data audit:

1. **`geodata_id` is not the primary key.** Upstream ids churn -- 351 state ids
   and 6,321 city ids changed meaning between two consecutive releases. The PK
   is Django's own; `geodata_id` is a plain indexed column recording where the
   row came from, and `stable_key` is the identity that survives a refresh.

2. **Rows are deactivated, never deleted.** When upstream drops a place that an
   application's history references, deleting it breaks that history. Instead
   `is_active` goes False and `superseded_by` points at the replacement, so old
   records keep resolving to something meaningful.

3. **Subdivisions nest.** `State.parent` is a self-FK and `depth` is the
   computed tree position, because the UK has 221 subdivisions across two
   levels and flattening them is what produced the orphan-FK bug in the
   dataset this replaces.

Apps that already have geography tables subclass the Abstract* bases and point
`GEODATA["MODELS"]` at their own models.
"""

from django.db import models


class GeodataQuerySet(models.QuerySet):
    def active(self):
        return self.filter(is_active=True)


class AbstractGeoRecord(models.Model):
    #: The upstream integer id. Indexed and useful for tracing, but NOT the
    #: identity: do not build foreign keys on it in your own tables.
    geodata_id = models.IntegerField(db_index=True)
    #: The identity that survives a dataset refresh (Decision 2).
    stable_key = models.CharField(max_length=200, db_index=True)
    name = models.CharField(max_length=200)
    normalized_name = models.CharField(max_length=200, db_index=True)

    is_active = models.BooleanField(
        default=True,
        help_text="False when upstream dropped this row but something still references it.",
    )
    superseded_by = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="supersedes",
        help_text="Set when this row was replaced during a dataset migration.",
    )

    objects = GeodataQuerySet.as_manager()

    class Meta:
        abstract = True

    def __str__(self):
        return self.name


class AbstractCountry(AbstractGeoRecord):
    iso2 = models.CharField(max_length=2, unique=True)
    iso3 = models.CharField(max_length=3, null=True, blank=True, db_index=True)
    numeric_code = models.CharField(max_length=3, null=True, blank=True)
    native = models.CharField(max_length=200, null=True, blank=True)
    capital = models.CharField(max_length=200, null=True, blank=True)
    phone_code = models.CharField(max_length=16, null=True, blank=True)
    currency = models.CharField(max_length=3, null=True, blank=True)
    currency_name = models.CharField(max_length=100, null=True, blank=True)
    currency_symbol = models.CharField(max_length=16, null=True, blank=True)
    tld = models.CharField(max_length=16, null=True, blank=True)
    region = models.CharField(max_length=100, null=True, blank=True, db_index=True)
    subregion = models.CharField(max_length=100, null=True, blank=True, db_index=True)
    nationality = models.CharField(max_length=100, null=True, blank=True)
    population = models.BigIntegerField(null=True, blank=True)
    area_sq_km = models.BigIntegerField(null=True, blank=True)
    postal_code_format = models.CharField(max_length=100, null=True, blank=True)
    postal_code_regex = models.CharField(max_length=255, null=True, blank=True)
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    emoji = models.CharField(max_length=16, null=True, blank=True)
    emoji_unicode = models.CharField(max_length=32, null=True, blank=True)
    wikidata_id = models.CharField(max_length=32, null=True, blank=True)
    timezones = models.JSONField(default=list, blank=True)

    #: For the 21 territories ISO 3166 lists at both levels (Decision 3).
    also_subdivision_of = models.JSONField(null=True, blank=True)

    class Meta:
        abstract = True
        ordering = ("name",)
        verbose_name_plural = "countries"


class AbstractState(AbstractGeoRecord):
    country = models.ForeignKey(
        "geodata.Country", on_delete=models.CASCADE, related_name="states"
    )
    #: The subdivision part only, e.g. "ABE".
    state_code = models.CharField(max_length=16, null=True, blank=True, db_index=True)
    #: The full ISO 3166-2 code, e.g. "GB-ABE". The preferred join key.
    iso3166_2 = models.CharField(max_length=16, null=True, blank=True, db_index=True)
    fips_code = models.CharField(max_length=16, null=True, blank=True)
    native = models.CharField(max_length=200, null=True, blank=True)
    type = models.CharField(max_length=100, null=True, blank=True, db_index=True)
    #: Upstream's semantic administrative level. Advisory -- it disagrees with
    #: the tree for ~1,000 states. Use `depth`.
    level = models.PositiveSmallIntegerField(null=True, blank=True)
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="children"
    )
    #: Computed from the parent chain. 1 = top level.
    depth = models.PositiveSmallIntegerField(default=1, db_index=True)
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    timezone = models.CharField(max_length=64, null=True, blank=True)
    population = models.BigIntegerField(null=True, blank=True)
    wikidata_id = models.CharField(max_length=32, null=True, blank=True)

    class Meta:
        abstract = True
        ordering = ("name",)
        constraints = [
            models.UniqueConstraint(
                fields=["country", "iso3166_2"],
                condition=models.Q(iso3166_2__isnull=False),
                name="%(app_label)s_%(class)s_unique_iso3166_2",
            ),
        ]
        indexes = [
            models.Index(fields=["country", "depth"]),
            models.Index(fields=["country", "normalized_name"]),
        ]


class AbstractCity(AbstractGeoRecord):
    country = models.ForeignKey(
        "geodata.Country", on_delete=models.CASCADE, related_name="cities"
    )
    state = models.ForeignKey(
        "geodata.State", on_delete=models.CASCADE, related_name="cities"
    )
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    timezone = models.CharField(max_length=64, null=True, blank=True)

    class Meta:
        abstract = True
        ordering = ("name",)
        indexes = [
            models.Index(fields=["country", "normalized_name"]),
            models.Index(fields=["state", "name"]),
        ]


class Country(AbstractCountry):
    class Meta(AbstractCountry.Meta):
        abstract = False
        db_table = "geodata_country"


class State(AbstractState):
    class Meta(AbstractState.Meta):
        abstract = False
        db_table = "geodata_state"


class City(AbstractCity):
    class Meta(AbstractCity.Meta):
        abstract = False
        db_table = "geodata_city"
