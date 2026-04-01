import csv
import re
from scholarly import scholarly


def extract_user_id(url):
    pattern = r"user=([^\&]+)"
    match = re.search(pattern, url)
    if match:
        return match.group(1)
    else:
        return None


def get_author_info(author_id):
    try:
        author = next(scholarly.search_author(author_id))
        author.fill()

        total_citations = author.citedby
        citations_since_2019 = author.citedby_2019

        h_index = author.hindex
        h_index_articles = [pub.bib['title'] for pub in author.hindex_articles]

        i10_index = author.i10index

        top_coauthors = [coauthor.name for coauthor in author.coauthors]

        return {
            "User ID": author_id,
            "Total Citations": total_citations,
            "Citations Since 2019": citations_since_2019,
            "h-index": h_index,
            "h-index Articles": h_index_articles,
            "i10-index": i10_index,
            "Top Co-authors": top_coauthors
        }
    except Exception as e:
        print(f"Error occurred while fetching data for user ID {author_id}: {str(e)}")
        return None


def main():
    input_file = "GMUurls.txt"  # File containing list of Google Scholar URLs

    output_file = "scholar_data.csv"  # Output file to save the data

    with open(input_file, "r") as f:
        urls = [line.strip() for line in f if line.strip()]

    user_ids = [extract_user_id(url) for url in urls]
    user_ids = [user_id for user_id in user_ids if user_id]  # Remove None values

    with open(output_file, "w", newline="") as csvfile:
        fieldnames = ["User ID", "Total Citations", "Citations Since 2019", "h-index",
                      "h-index Articles", "i10-index", "Top Co-authors"]
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()

        for user_id in user_ids:
            author_info = get_author_info(user_id)
            if author_info:
                writer.writerow(author_info)
                print(f"Data collected for user ID: {user_id}")
            else:
                print(f"No data found for user ID: {user_id}")


if __name__ == "__main__":
    main()
