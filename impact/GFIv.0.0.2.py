from flask import Flask
from scholarly import scholarly

app = Flask(__name__)


@app.route('/')
def get_author_info():
    author = scholarly.search_author_id("sH44LC4AAAAJ")
    author_info = scholarly.fill(author, sections=[])

    html_output = "<h1>Author Details</h1>"

    # Format the author information as HTML
    for key, value in author_info.items():
        html_output += f"<p><b>{key}:</b> {value}</p>"

    return html_output


if __name__ == '__main__':
    app.run(debug=True)
