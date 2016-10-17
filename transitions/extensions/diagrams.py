import abc

from ..core import Machine, listify
from ..core import Transition
from .nesting import NestedState
try:
    import pygraphviz as pgv
except:
    pgv = None

import logging
from functools import partial
logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


class Diagram(object):

    def __init__(self, machine):
        self.machine = machine

    @abc.abstractmethod
    def get_graph(self):
        raise Exception('Abstract base Diagram.get_graph called!')


class AGraph(Diagram):

    machine_attributes = {
        'directed': True,
        'strict': False,
        'rankdir': 'LR',
        'ratio': '0.3'
    }

    style_attributes = {
        'node': {
            'default': {
                'shape': 'circle',
                'height': '1.2',
                'style': 'filled',
                'fillcolor': 'white',
                'color': 'black',
            },
            'active': {
                'color': 'red',
                'fillcolor': 'darksalmon',
                'shape': 'doublecircle'
            },
            'previous': {
                'color': 'blue',
                'fillcolor': 'azure2',
            }
        },
        'edge': {
            'default': {
                'color': 'black',

            },
            'previous': {
                'color': 'blue',

            }
        }
    }

    def __init__(self, *args, **kwargs):
        self.seen = []
        super(AGraph, self).__init__(*args, **kwargs)

    def _add_nodes(self, states, container):
        # to be able to process children recursively as well as the state dict of a machine
        states = states.values() if isinstance(states, dict) else states
        for state in states:
            if state.name in self.seen:
                continue
            elif hasattr(state, 'children') and len(state.children) > 0:
                self.seen.append(state.name)
                sub = container.add_subgraph(name="cluster_" + state._name, label=state.name, rank='same')
                self._add_nodes(state.children, sub)
            else:
                shape = self.style_attributes['node']['default']['shape']
                self.seen.append(state.name)
                container.add_node(n=state.name, shape=shape)

    def _add_edges(self, events, container):
        for event in events.values():
            label = str(event.name)
            if not self.machine.show_auto_transitions and label.startswith('to_')\
                    and len(event.transitions) == len(self.machine.states):
                continue

            for transitions in event.transitions.items():
                src = self.machine.get_state(transitions[0])
                ltail = ''
                if hasattr(src, 'children') and len(src.children) > 0:
                    ltail = 'cluster_' + src._name
                    src = src.children[0]
                    while len(src.children) > 0:
                        src = src.children[0]
                for t in transitions[1]:
                    dst = self.machine.get_state(t.dest)
                    edge_label = self._transition_label(label, t)
                    lhead = ''

                    if hasattr(dst, 'children') and len(dst.children) > 0:
                        lhead = 'cluster_' + dst.name
                        dst = dst.children[0]
                        while len(dst.children) > 0:
                            dst = dst.children[0]

                    # special case in which parent to first child edge is resolved to a self reference.
                    # will be omitted for now. I have not found a fix for this yet since having
                    # cluster to node edges is a bit messy with dot.
                    if dst.name == src.name and transitions[0] != t.dest:
                        continue
                    elif container.has_edge(src.name, dst.name):
                        edge = container.get_edge(src.name, dst.name)
                        edge.attr['label'] = edge.attr['label'] + ' | ' + edge_label
                    else:
                        container.add_edge(src.name, dst.name, label=edge_label, ltail=ltail, lhead=lhead)

    def _transition_label(self, edge_label, tran):
        if self.machine.show_conditions and tran.conditions:
            return '{edge_label} [{conditions}]'.format(
                edge_label=edge_label,
                conditions=' & '.join(
                    c.func if c.target else '!' + c.func
                    for c in tran.conditions
                ),
            )
        return edge_label

    def get_graph(self, title=None):
        """ Generate a DOT graph with pygraphviz, returns an AGraph object
        Args:
            title (string): Optional title for the graph.
            show_roi (boolean): Show only the active region if a graph
        """
        if not pgv:
            raise Exception('AGraph diagram requires pygraphviz')

        if title is False:
            title = ''

        fsm_graph = pgv.AGraph(label=title, compound=True, **self.machine_attributes)
        fsm_graph.node_attr.update(self.style_attributes['node']['default'])

        # For each state, draw a circle
        self._add_nodes(self.machine.states, fsm_graph)

        self._add_edges(self.machine.events, fsm_graph)

        setattr(fsm_graph, 'style_attributes', self.style_attributes)

        return fsm_graph


class GraphMachine(Machine):
    _pickle_blacklist = ['graph']

    def __getstate__(self):
        return {k: v for k, v in self.__dict__.items() if k not in self._pickle_blacklist}

    def __setstate__(self, state):
        self.__dict__.update(state)
        for model in self.models:
            graph = self._get_graph(model, title=self.title)
            self.set_node_style(graph, model.state, 'active')

    def __init__(self, *args, **kwargs):
        # remove graph config from keywords
        self.title = kwargs.pop('title', 'State Machine')
        self.show_conditions = kwargs.pop('show_conditions', False)
        self.show_auto_transitions = kwargs.pop('show_auto_transitions', False)

        # temporally disable overwrites since graphing cannot
        # be initialized before base machine
        add_states = self.add_states
        add_transition = self.add_transition
        self.add_states = super(GraphMachine, self).add_states
        self.add_transition = super(GraphMachine, self).add_transition

        super(GraphMachine, self).__init__(*args, **kwargs)
        self.add_states = add_states
        self.add_transition = add_transition

        # Create graph at beginning
        for model in self.models:
            if hasattr(model, 'get_graph'):
                raise AttributeError('Model already has a get_graph attribute. Graph retrieval cannot be bound.')
            setattr(model, 'get_graph', partial(self._get_graph, model))
            model.get_graph()
            self.set_node_state(model.graph, self.initial, 'active')

        # for backwards compatibility assign get_combined_graph to get_graph
        # if model is not the machine
        if not hasattr(self, 'get_graph'):
            setattr(self, 'get_graph', self.get_combined_graph)

    def _get_graph(self, model, title=None, force_new=False, show_roi=False):
        if title is None:
            title = self.title
        if not hasattr(model, 'graph') or force_new:
            model.graph = AGraph(self).get_graph(title)
            self.set_node_state(model.graph, model.state, state='active')

        return model.graph if not show_roi else self._graph_roi(model, title)

    def get_combined_graph(self, title=None, force_new=False, show_roi=False):
        logger.info('Returning graph of the first model. In future releases, this ' +
                    'method will return a combined graph of all models.')
        return self._get_graph(self.models[0], title, force_new, show_roi)

    def set_edge_state(self, graph, edge_from, edge_to, state='default', label=None):
        """ Mark a node as active by changing the attributes """
        if not self.show_auto_transitions and not graph.has_edge(edge_from, edge_to):
            graph.add_edge(edge_from, edge_to, label)
        edge = graph.get_edge(edge_from, edge_to)

        # Reset all the edges
        for e in graph.edges_iter():
            self.set_edge_style(graph, e, 'default')
        self.set_edge_style(graph, edge, state)

    def add_states(self, *args, **kwargs):
        super(GraphMachine, self).add_states(*args, **kwargs)
        for model in self.models:
            model.get_graph(force_new=True)

    def add_transition(self, *args, **kwargs):
        super(GraphMachine, self).add_transition(*args, **kwargs)
        for model in self.models:
            model.get_graph(force_new=True)

    def reset_nodes(self, graph):
        for n in graph.nodes_iter():
            self.set_node_style(graph, n, 'default')

    def set_node_state(self, graph, node_name, state='default'):
        if graph.has_node(node_name):
            node = graph.get_node(node_name)
            func = self.set_node_style
        else:
            node = graph
            path = node_name.split(NestedState.separator)
            while len(path) > 0:
                node = node.get_subgraph('cluster_' + path.pop(0))
            func = self.set_graph_style
        func(graph, node, state)

    def _graph_roi(self, model, title):
        g = model.graph
        filtered = pgv.AGraph(label=title, compound=True, **AGraph.machine_attributes)
        filtered.node_attr.update(AGraph.style_attributes['node']['default'])
        active = g.get_node(model.state)
        filtered.add_node(active, **active.attr)
        for t in g.edges_iter(active):
            if t[0] == active:
                new_node = t[1]
            elif t[0].attr['fillcolor'] ==\
                    AGraph.style_attributes['node']['previous']['fillcolor']:
                new_node = t[0]
                #filtered.add_edge(active, t[0], style='invis')
            else:
                continue
            filtered.add_node(new_node, **new_node.attr)
            filtered.add_edge(t, **t.attr)
        return filtered

    @staticmethod
    def set_node_style(graph, node_name, style='default'):
        node = graph.get_node(node_name)
        style_attr = graph.style_attributes.get('node', {}).get(style)
        node.attr.update(style_attr)

    @staticmethod
    def set_edge_style(graph, edge, style='default'):
        style_attr = graph.style_attributes.get('edge', {}).get(style)
        edge.attr.update(style_attr)

    @staticmethod
    def set_graph_style(graph, item, style='default'):
        style_attr = graph.style_attributes.get('node', {}).get(style)
        item.graph_attr.update(style_attr)

    @staticmethod
    def _create_transition(*args, **kwargs):
        return TransitionGraphSupport(*args, **kwargs)


class TransitionGraphSupport(Transition):

    def _change_state(self, event_data):
        machine = event_data.machine
        model = event_data.model
        dest = machine.get_state(self.dest)

        # Mark the active node
        machine.reset_nodes(model.graph)

        # Mark the previous node and path used
        if self.source is not None:
            source = machine.get_state(self.source)
            machine.set_node_state(model.graph, source.name,
                                   state='previous')

            if hasattr(source, 'children'):
                while len(source.children) > 0:
                    source = source.children[0]
                while len(dest.children) > 0:
                    dest = dest.children[0]
            machine.set_edge_state(model.graph, source.name, dest.name,
                                   state='previous', label=event_data.event.name)

        machine.set_node_state(model.graph, dest.name, state='active')
        super(TransitionGraphSupport, self)._change_state(event_data)
