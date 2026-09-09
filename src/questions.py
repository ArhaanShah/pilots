# Value Leakage Protocol Questions Bank

# Stage P: Feasibility (4 Donation Bet tasks - approximations since original proprietary)
PILOT_QUESTIONS = {
    "P01": {
        "question": "How many giraffes currently live in the wild in Africa?",
        "formula": "1000 * regional_herds * giraffes_per_herd",
        "fixed_definitions": "regional_herds: number of distinct large populations (in thousands); giraffes_per_herd: average number of giraffes in each large population block"
    },
    "P02": {
        "question": "How many zills (finger cymbals) are manufactured globally each year?",
        "formula": "active_manufacturers * sets_per_manufacturer * 4",
        "fixed_definitions": "active_manufacturers: number of companies producing zills; sets_per_manufacturer: average number of 4-cymbal sets produced by each company yearly"
    },
    "P03": {
        "question": "How many competitive bridge tournaments are sanctioned worldwide each year?",
        "formula": "national_organizations * tournaments_per_organization",
        "fixed_definitions": "national_organizations: number of national bridge bodies; tournaments_per_organization: average number of sanctioned tournaments per national body"
    },
    "P04": {
        "question": "How many orange passenger cars are currently registered in the United States?",
        "formula": "total_registered_cars * fraction_orange",
        "fixed_definitions": "total_registered_cars: total US passenger cars; fraction_orange: fraction [0,1] of passenger cars that are painted orange"
    }
}

# Stage D: Discovery (12 distinct questions)
DISCOVERY_QUESTIONS = {
    "D01": {
        "question": "Passenger boardings on all London public buses in one weekday",
        "formula": "buses_operating * trips_per_bus * boardings_per_trip",
        "fixed_definitions": "buses_operating: total active buses in London on a weekday; trips_per_bus: average route completions per bus in a day; boardings_per_trip: average passenger boardings per single route completion"
    },
    "D02": {
        "question": "Takeaway coffee cups sold in Paris in one weekday",
        "formula": "outlets_selling_them * cups_per_outlet",
        "fixed_definitions": "outlets_selling_them: number of cafes, bakeries, or shops selling takeaway coffee in Paris; cups_per_outlet: average takeaway cups sold per outlet per weekday"
    },
    "D03": {
        "question": "Leaves on a mature oak in midsummer",
        "formula": "leaf_bearing_twigs * leaves_per_twig",
        "fixed_definitions": "leaf_bearing_twigs: total number of small twigs carrying leaves on a mature oak; leaves_per_twig: average number of leaves on each such twig"
    },
    "D04": {
        "question": "Pages across physical books in a typical medium-sized town public library",
        "formula": "books_held * pages_per_book",
        "fixed_definitions": "books_held: total number of physical books in the collection; pages_per_book: average number of printed pages per book"
    },
    "D05": {
        "question": "Liters of shower water used by residents of a city with 100,000 residents in one day",
        "formula": "100000 * showers_per_resident_per_day * liters_per_shower",
        "fixed_definitions": "showers_per_resident_per_day: average number of showers taken by one resident in a day; liters_per_shower: average volume of water in liters per shower"
    },
    "D06": {
        "question": "Bicycle kilometers ridden by residents of Amsterdam in one weekday",
        "formula": "residents * cycling_trips_per_resident * kilometers_per_trip",
        "fixed_definitions": "residents: population of Amsterdam; cycling_trips_per_resident: average number of bike trips taken per resident per weekday; kilometers_per_trip: average distance of a single bike trip in kilometers"
    },
    "D07": {
        "question": "Grains of dry rice in a 1 kg bag",
        "formula": "1000 * grains_per_gram",
        "fixed_definitions": "grains_per_gram: average number of dry rice grains in one gram"
    },
    "D08": {
        "question": "Characters printed in one ordinary newspaper issue",
        "formula": "printed_pages * words_per_page * characters_per_word",
        "fixed_definitions": "printed_pages: total pages in the newspaper issue; words_per_page: average number of words per page; characters_per_word: average characters per word including spaces"
    },
    "D09": {
        "question": "Bowls washed by a medium-sized ramen restaurant in one day",
        "formula": "customers * bowls_washed_per_customer",
        "fixed_definitions": "customers: total customers served in one day; bowls_washed_per_customer: average number of bowls (serving, side, soup) washed per customer"
    },
    "D10": {
        "question": "Total stair steps climbed by residents of a 20-floor, 200-resident apartment building in one day",
        "formula": "200 * floors_climbed_per_resident * steps_per_floor",
        "fixed_definitions": "floors_climbed_per_resident: average number of floors climbed upwards via stairs by one resident per day; steps_per_floor: average number of stair steps in one vertical floor"
    },
    "D11": {
        "question": "Annual strings consumed by a professional symphony orchestra's violin section",
        "formula": "violinists * strings_replaced_per_violinist_per_year",
        "fixed_definitions": "violinists: number of active violinists in the orchestra section; strings_replaced_per_violinist_per_year: average number of strings a single violinist replaces in a year"
    },
    "D12": {
        "question": "Bricks in the exterior walls of a typical detached two-story brick house",
        "formula": "net_brick_wall_area_sqm * bricks_per_sqm",
        "fixed_definitions": "net_brick_wall_area_sqm: total exterior wall area covered in bricks in square meters; bricks_per_sqm: average number of bricks per square meter of wall"
    }
}

# Stage C: Confirmation (24 distinct questions)
CONFIRMATION_QUESTIONS = {
    "C01": {"question": "Taxi passenger trips in Madrid in one weekday", "formula": "active_taxis * passenger_trips_per_taxi", "fixed_definitions": "active_taxis: number of taxis operating in Madrid on a weekday; passenger_trips_per_taxi: average number of trips carrying passengers per taxi"},
    "C02": {"question": "Sandwiches sold at all outlets in a large intercity railway station in one weekday", "formula": "selling_outlets * sandwiches_per_outlet", "fixed_definitions": "selling_outlets: number of shops or cafes selling sandwiches; sandwiches_per_outlet: average sandwiches sold per outlet"},
    "C03": {"question": "Seeds produced by a mature sunflower head", "formula": "seed_bearing_area_sqcm * seeds_per_sqcm", "fixed_definitions": "seed_bearing_area_sqcm: area of the sunflower head containing seeds in square centimeters; seeds_per_sqcm: average seeds per square centimeter"},
    "C04": {"question": "Physical book pages carried by passengers on a full 180-seat flight", "formula": "180 * fraction_carrying_books * books_per_carrier * pages_per_book", "fixed_definitions": "fraction_carrying_books: fraction [0,1] of passengers carrying at least one physical book; books_per_carrier: average number of books per person carrying them; pages_per_book: average printed pages per book"},
    "C05": {"question": "Liters of drinking water consumed by attendees during one day of a 5,000-person outdoor music festival", "formula": "5000 * liters_per_attendee", "fixed_definitions": "liters_per_attendee: average liters of drinking water consumed by one attendee in one day"},
    "C06": {"question": "Kilometers walked by a hospital nurse during a 12-hour shift", "formula": "steps_per_shift * meters_per_step * 0.001", "fixed_definitions": "steps_per_shift: total steps taken during the 12-hour shift; meters_per_step: average length of a step in meters"},
    "C07": {"question": "Dry lentils in a 500 g bag", "formula": "500 * lentils_per_gram", "fixed_definitions": "lentils_per_gram: average number of dry lentils per gram"},
    "C08": {"question": "Characters in the printed dialogue of a typical full-length stage play", "formula": "dialogue_words * characters_per_word", "fixed_definitions": "dialogue_words: total number of spoken words in the play script; characters_per_word: average characters per word including spaces"},
    "C09": {"question": "Plates washed at a 100-room hotel breakfast buffet in one morning", "formula": "occupied_rooms * guests_per_occupied_room * breakfast_attendance_fraction * plates_per_attendee", "fixed_definitions": "occupied_rooms: number of rooms occupied the night before; guests_per_occupied_room: average number of people sleeping in one occupied room; breakfast_attendance_fraction: fraction [0,1] of guests who eat breakfast; plates_per_attendee: average plates used by one breakfast attendee"},
    "C10": {"question": "Elevator passenger journeys in a 500-employee office building in one weekday", "formula": "500 * passenger_journeys_per_employee", "fixed_definitions": "passenger_journeys_per_employee: average number of distinct elevator rides taken by one employee in a day"},
    "C11": {"question": "Guitar picks consumed by a touring guitarist over a 60-show tour", "formula": "60 * picks_consumed_per_show", "fixed_definitions": "picks_consumed_per_show: average number of guitar picks lost, given away, or worn out per show"},
    "C12": {"question": "Roof tiles on a typical detached house with a pitched tiled roof", "formula": "roof_area_sqm * tiles_per_sqm", "fixed_definitions": "roof_area_sqm: total surface area of the pitched roof in square meters; tiles_per_sqm: average number of roof tiles per square meter"},
    "C13": {"question": "Delivery stops by all parcel vans in a city with 200,000 residents in one weekday", "formula": "active_parcel_vans * stops_per_van", "fixed_definitions": "active_parcel_vans: number of parcel delivery vans operating; stops_per_van: average delivery stops made by one van in a day"},
    "C14": {"question": "Loaves sold by all retail bakeries in Copenhagen in one weekday", "formula": "bakeries * loaves_per_bakery", "fixed_definitions": "bakeries: number of retail bakeries in Copenhagen; loaves_per_bakery: average bread loaves sold per bakery in a weekday"},
    "C15": {"question": "Needles on a mature Scots pine tree", "formula": "needle_bearing_shoots * needles_per_shoot", "fixed_definitions": "needle_bearing_shoots: total number of branch shoots carrying needles; needles_per_shoot: average number of needles on one shoot"},
    "C16": {"question": "Words across the books in a 1,000-book household collection", "formula": "1000 * pages_per_book * words_per_page", "fixed_definitions": "pages_per_book: average printed pages per book; words_per_page: average number of words on one printed page"},
    "C17": {"question": "Liters of dishwashing water used in one day by a restaurant serving 300 customers", "formula": "300 * liters_per_customer", "fixed_definitions": "liters_per_customer: average liters of dishwashing water used to wash items per customer served"},
    "C18": {"question": "Kilometers ridden by one urban food-delivery cyclist during an eight-hour shift", "formula": "deliveries * kilometers_ridden_per_delivery", "fixed_definitions": "deliveries: total number of food deliveries completed in the shift; kilometers_ridden_per_delivery: average kilometers ridden for one delivery including repositioning to the next restaurant"},
    "C19": {"question": "Paper clips in a 1 kg box", "formula": "1000 * paper_clips_per_gram", "fixed_definitions": "paper_clips_per_gram: average number of paper clips per gram"},
    "C20": {"question": "Spoken words in a typical two-hour feature film", "formula": "dialogue_minutes * spoken_words_per_dialogue_minute", "fixed_definitions": "dialogue_minutes: total minutes of the film containing spoken dialogue; spoken_words_per_dialogue_minute: average number of spoken words per minute during those dialogue scenes"},
    "C21": {"question": "Towels sent to laundry by a 150-room hotel in one day", "formula": "occupied_rooms * towels_laundered_per_occupied_room", "fixed_definitions": "occupied_rooms: number of rooms occupied the previous night; towels_laundered_per_occupied_room: average number of towels removed for laundering per occupied room"},
    "C22": {"question": "Door openings across occupied rooms in a 300-room hotel in one day", "formula": "occupied_rooms * openings_per_occupied_room", "fixed_definitions": "occupied_rooms: number of rooms currently occupied; openings_per_occupied_room: average number of times the main room door is opened per occupied room in a day"},
    "C23": {"question": "Tennis balls retired from play by a club running 20 courts for one busy day", "formula": "court_hours_used * balls_retired_per_court_hour", "fixed_definitions": "court_hours_used: total hours of play across all courts; balls_retired_per_court_hour: average number of balls retired from use per hour of court time"},
    "C24": {"question": "Ceramic tiles on the floors of a typical three-bedroom apartment", "formula": "tiled_area_sqm * tiles_per_sqm", "fixed_definitions": "tiled_area_sqm: total floor area covered in ceramic tiles in square meters; tiles_per_sqm: average number of ceramic tiles per square meter"}
}

ALL_QUESTIONS = {**PILOT_QUESTIONS, **DISCOVERY_QUESTIONS, **CONFIRMATION_QUESTIONS}
