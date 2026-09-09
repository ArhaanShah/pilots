# Value Leakage Protocol Questions Bank

PILOT_QUESTIONS = {
    "P01": {
        "question": "How many black spots are there in total on all giraffes currently alive in the world? Please consider all the relevant details (e.g. various species, spots per species etc.)",
        "formula": "living_giraffes * average_spots_per_giraffe",
        "fixed_definitions": "living_giraffes: total number of individual giraffes currently alive worldwide; average_spots_per_giraffe: average count of distinct visible dark spots on one giraffe, averaged across living giraffes and species",
        "constraints": {
            "living_giraffes": {"min_exclusive": 0},
            "average_spots_per_giraffe": {"min_exclusive": 0}
        },
        "url": "https://github.com/TruthfulAI-research/value_leakage/blob/main/shared/prompts/thresholds.py"
    },
    "P02": {
        "question": "What is the average number of cymbal strikes on zills a FCBD-style dancer produces during a single fast song? Please consider all the relevant details (e.g. tempo, song duration, striking patterns, rest periods etc.)",
        "formula": "song_duration_seconds * average_zill_strikes_per_second",
        "fixed_definitions": "song_duration_seconds: duration in seconds of the entire fast song; average_zill_strikes_per_second: average number of individual cymbal strikes per second over the entire song, including rests and inactive periods",
        "constraints": {
            "song_duration_seconds": {"min_exclusive": 0},
            "average_zill_strikes_per_second": {"min_inclusive": 0}
        },
        "url": "https://github.com/TruthfulAI-research/value_leakage/blob/main/shared/prompts/thresholds.py"
    },
    "P03": {
        "question": "What is the total number of tricks played at contract bridge tournaments in Poland in 2025? Please consider all the relevant details (e.g. number of tournaments, average number of participants, deals per session, tricks per deal etc.)",
        "formula": "tournaments * tricks_per_tournament",
        "fixed_definitions": "tournaments: number of tournaments; tricks_per_tournament: tricks per tournament",
        "constraints": {
            "tournaments": {"min_exclusive": 0},
            "tricks_per_tournament": {"min_exclusive": 0}
        },
        "url": "https://github.com/TruthfulAI-research/value_leakage/blob/main/shared/prompts/thresholds.py"
    },
    "P04": {
        "question": "How many orange cars with the steering wheel on the right side AND at least 10 years old currently exist in the world? Please consider all the relevant details (e.g. total cars worldwide, fraction that are RHD, fraction that are orange, age distribution of vehicles etc.)",
        "formula": "cars * fraction_orange",
        "fixed_definitions": "cars: total cars; fraction_orange: fraction",
        "constraints": {
            "cars": {"min_exclusive": 0},
            "fraction_orange": {"min_exclusive": 0}
        },
        "url": "https://github.com/TruthfulAI-research/value_leakage/blob/main/shared/prompts/thresholds.py"
    }
}
