def lookup_description(spirit_name):
    # TODO: Search online sources for a description of the spirit
    return f"Description for {spirit_name} is not implemented yet."


def enrich_dataframe_with_descriptions(df):
    df["Description"] = df["BRAND NAME"].apply(lookup_description)
    return df