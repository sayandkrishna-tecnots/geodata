import os
import json
import urllib.request
import logging
from django.core.management.base import BaseCommand
from django.db import transaction
from django.conf import settings
from geography.models import Country, State, City

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = "Seeds all missing countries, states, and cities globally using react-country-state-city dataset while preserving existing records."

    # CDN URL definitions
    COUNTRIES_URL = "https://venkatmcajj.github.io/react-country-state-city/data/countriesminified.json"
    STATES_URL = "https://venkatmcajj.github.io/react-country-state-city/data/statesminified.json"
    CITIES_URL = "https://venkatmcajj.github.io/react-country-state-city/data/citiesminified.json"

    # Countries to preserve exactly as-is without any modifications or imports
    PRESERVED_COUNTRIES = {"AE", "IN", "NG", "US"}

    def handle(self, *args, **options):
        self.stdout.write(self.style.WARNING("Starting global geography seeding process..."))
        
        # 1. Ensure data directory exists
        data_dir = os.path.join(settings.BASE_DIR, "geography", "data")
        os.makedirs(data_dir, exist_ok=True)

        # 2. Download files if not present locally
        countries_path = os.path.join(data_dir, "countries.json")
        states_path = os.path.join(data_dir, "states.json")
        cities_path = os.path.join(data_dir, "cities.json")

        self.ensure_file(self.COUNTRIES_URL, countries_path, "countries")
        self.ensure_file(self.STATES_URL, states_path, "states")
        self.ensure_file(self.CITIES_URL, cities_path, "cities")

        # 3. Load the JSONs
        self.stdout.write("Loading cached geography files...")
        with open(countries_path, "r", encoding="utf-8") as f:
            countries_data = json.load(f)
        with open(states_path, "r", encoding="utf-8") as f:
            states_data = json.load(f)
        with open(cities_path, "r", encoding="utf-8") as f:
            cities_data = json.load(f)

        # Index states by country ID
        states_by_country = {item["id"]: item.get("states", []) for item in states_data}

        # Index cities by country ID and state ID
        cities_by_country_and_state = {}
        for item in cities_data:
            country_id = item["id"]
            for state_item in item.get("states", []):
                state_id = state_item["id"]
                cities_by_country_and_state[(country_id, state_id)] = state_item.get("cities", [])

        # Start database seeding within a transaction for speed and safety
        try:
            with transaction.atomic():
                self.seed_geography(countries_data, states_by_country, cities_by_country_and_state)
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Seeding failed: {str(e)}"))
            logger.exception("Geography seeding exception:")
            raise e

    def ensure_file(self, url, path, name):
        """Ensures that the JSON file exists locally, downloading it from the CDN if necessary."""
        if not os.path.exists(path):
            self.stdout.write(f"Downloading {name} from CDN...")
            req = urllib.request.Request(
                url, 
                headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
            )
            with urllib.request.urlopen(req) as response:
                content = response.read()
                with open(path, "wb") as f:
                    f.write(content)
            self.stdout.write(self.style.SUCCESS(f"Successfully downloaded and cached {name} locally!"))
        else:
            self.stdout.write(self.style.SUCCESS(f"Using locally cached {name} file."))

    def seed_geography(self, countries_data, states_by_country, cities_by_country_and_state):
        """Main seeding logic."""
        # Query existing countries, states, and cities to prevent duplicate insert attempts and keep existing rows intact
        self.stdout.write("Querying existing database geography records...")
        existing_countries = {c.code: c for c in Country.objects.all()}
        existing_states = {(s.country_id, s.name.lower().strip()): s for s in State.objects.all()}
        existing_cities = {(c.state_id, c.name.lower().strip()) for c in City.objects.all()}

        # Map to track which preserved countries actually exist in the DB right now
        already_present_preserved_countries = {
            code for code in self.PRESERVED_COUNTRIES if code in existing_countries
        }

        # Keep track of states seen in current run to prevent inner-loop unique constraint violations
        seen_states = set(existing_states.keys())

        countries_to_create = []
        states_to_create = []
        
        # Step A: Seed Countries
        self.stdout.write("Processing countries...")
        country_mapping = {}  # maps json country_id to Country object
        
        for c in countries_data:
            code = c.get("iso2", "").upper().strip()
            if not code or len(code) != 2:
                continue
            
            # Skip preserved countries (IN, NG, AE, US) only if they already exist in the database
            if code in self.PRESERVED_COUNTRIES:
                if code in already_present_preserved_countries:
                    country_mapping[c["id"]] = existing_countries[code]
                    continue
                
            name = c.get("name", "").strip()
            
            if code in existing_countries:
                # Update name if changed, otherwise keep it
                country_obj = existing_countries[code]
                if country_obj.name != name:
                    country_obj.name = name
                    country_obj.save(update_fields=["name"])
                country_mapping[c["id"]] = country_obj
            else:
                country_obj = Country(code=code, name=name)
                countries_to_create.append(country_obj)
                # We will map it temporary, after bulk_create we will map properly by code
                country_mapping[c["id"]] = country_obj

        if countries_to_create:
            self.stdout.write(f"Bulk creating {len(countries_to_create)} new countries...")
            Country.objects.bulk_create(countries_to_create)
            # Re-fetch all countries to populate country_mapping and existing_countries with valid primary keys
            refetched_countries = {c.code: c for c in Country.objects.all()}
            existing_countries.update(refetched_countries)
            for c in countries_data:
                code = c.get("iso2", "").upper().strip()
                if code in refetched_countries:
                    country_mapping[c["id"]] = refetched_countries[code]

        # Step B: Seed States
        self.stdout.write("Processing states / administrative regions...")
        state_mapping = {}  # maps (country_id, json_state_id) to State object
        fallback_states_to_create = []  # states generated as fallback for countries without states

        for c in countries_data:
            country_id = c["id"]
            code = c.get("iso2", "").upper().strip()
            country_obj = country_mapping.get(country_id)
            if not country_obj:
                continue

            json_states = states_by_country.get(country_id, [])
            
            # Defensive Fallback: If country has no states, create a mock state with same name as country
            if not json_states:
                fallback_name = country_obj.name
                fallback_code = country_obj.code
                key = (country_obj.id, fallback_name.lower().strip())
                
                if key in seen_states:
                    if key in existing_states:
                        state_mapping[key] = existing_states[key]
                else:
                    state_obj = State(country=country_obj, name=fallback_name, code=fallback_code)
                    fallback_states_to_create.append((state_obj, key))
                    seen_states.add(key)
                continue

            for s in json_states:
                state_name = s.get("name", "").strip()
                state_code = s.get("state_code", "").strip()[:10]
                if not state_name:
                    continue
                
                key = (country_obj.id, state_name.lower().strip())
                if key in seen_states:
                    if key in existing_states:
                        state_obj = existing_states[key]
                        if state_obj.code != state_code:
                            state_obj.code = state_code
                            state_obj.save(update_fields=["code"])
                        state_mapping[(country_obj.id, s["id"])] = state_obj
                else:
                    state_obj = State(country=country_obj, name=state_name, code=state_code)
                    states_to_create.append((state_obj, (country_obj.id, s["id"])))
                    seen_states.add(key)

        # Bulk create standard new states
        if states_to_create:
            self.stdout.write(f"Bulk creating {len(states_to_create)} new states...")
            State.objects.bulk_create([x[0] for x in states_to_create])
            # Re-fetch new states to get their IDs and map them
            db_states = {
                (s.country_id, s.name.lower().strip()): s 
                for s in State.objects.all()
            }
            existing_states.update(db_states)
            for state_obj, map_key in states_to_create:
                db_key = (state_obj.country_id, state_obj.name.lower().strip())
                if db_key in db_states:
                    state_mapping[map_key] = db_states[db_key]

        # Bulk create fallback states
        if fallback_states_to_create:
            self.stdout.write(f"Bulk creating {len(fallback_states_to_create)} fallback states...")
            State.objects.bulk_create([x[0] for x in fallback_states_to_create])
            db_states = {
                (s.country_id, s.name.lower().strip()): s 
                for s in State.objects.all()
            }
            existing_states.update(db_states)
            for state_obj, map_key in fallback_states_to_create:
                if map_key in db_states:
                    state_mapping[map_key] = db_states[map_key]

        # Step C: Seed Cities
        self.stdout.write("Processing cities...")
        cities_to_create = []
        fallback_cities_to_create = []

        for c in countries_data:
            country_id = c["id"]
            code = c.get("iso2", "").upper().strip()
            country_obj = country_mapping.get(country_id)
            if not country_obj:
                continue

            json_states = states_by_country.get(country_id, [])
            capital_city = c.get("capital", "").strip()

            # Handle mock fallback cities for countries without states
            if not json_states:
                fallback_state_key = (country_obj.id, country_obj.name.lower().strip())
                state_obj = state_mapping.get(fallback_state_key)
                if state_obj:
                    fallback_city_name = capital_city if capital_city else country_obj.name
                    city_key = (state_obj.id, fallback_city_name.lower().strip())
                    if city_key not in existing_cities:
                        city_obj = City(state=state_obj, name=fallback_city_name)
                        fallback_cities_to_create.append(city_obj)
                        existing_cities.add(city_key)
                continue

            # Handle cities for standard states
            for s in json_states:
                state_id = s["id"]
                state_obj = state_mapping.get((country_obj.id, state_id))
                if not state_obj:
                    continue

                json_cities = cities_by_country_and_state.get((country_id, state_id), [])
                
                # Defensive Fallback: If state has 0 cities in dataset, create fallback city named after state
                if not json_cities:
                    city_key = (state_obj.id, state_obj.name.lower().strip())
                    if city_key not in existing_cities:
                        city_obj = City(state=state_obj, name=state_obj.name)
                        fallback_cities_to_create.append(city_obj)
                        existing_cities.add(city_key)
                    continue

                for ci in json_cities:
                    city_name = ci.get("name", "").strip()
                    if not city_name:
                        continue
                    
                    city_key = (state_obj.id, city_name.lower().strip())
                    if city_key not in existing_cities:
                        city_obj = City(state=state_obj, name=city_name)
                        cities_to_create.append(city_obj)
                        existing_cities.add(city_key)

        # Bulk create all standard cities in batch sizes for performance
        if cities_to_create:
            self.stdout.write(f"Bulk creating {len(cities_to_create)} new cities in batches...")
            City.objects.bulk_create(cities_to_create, batch_size=2000)

        # Bulk create fallback cities
        if fallback_cities_to_create:
            self.stdout.write(f"Bulk creating {len(fallback_cities_to_create)} fallback cities...")
            City.objects.bulk_create(fallback_cities_to_create)

        self.stdout.write(self.style.SUCCESS("Database geography seeding completed successfully!"))
        
        # Verify counts in database
        self.stdout.write(self.style.SUCCESS(f"Total Countries: {Country.objects.count()}"))
        self.stdout.write(self.style.SUCCESS(f"Total States: {State.objects.count()}"))
        self.stdout.write(self.style.SUCCESS(f"Total Cities: {City.objects.count()}"))
