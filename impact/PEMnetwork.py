import scholar_network as sn
import matplotlib.pyplot as plt
import networkx as nx

# Scrape data for a single author
sn.scrape_single_author(scholar_id='sH44LC4AAAAJ', scholar_name='Patrick McKnight', preferred_browser='chrome')

# Build the graph
g = sn.build_graph()

# Get the top 10 edge ranks
top_edges = g.edge_rank(limit=10)

# Create a directed graph from the top ranked edges
G = nx.DiGraph()
G.add_edges_from([(edge[0], edge[1]) for edge in top_edges])

# Draw the graph
pos = nx.spring_layout(G)  # Position nodes using Fruchterman-Reingold force-directed algorithm
nx.draw(G, pos, with_labels=True, node_size=2000, node_color='skyblue', font_size=10, font_weight='bold', edge_color='gray', arrows=True, arrowstyle='->')
labels = nx.get_edge_attributes(G, 'weight')
nx.draw_networkx_edge_labels(G, pos, edge_labels=labels)
plt.title('Top 10 Edge Rank Network Graph')
plt.show()
