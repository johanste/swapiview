import json
import logging
import typing

import openapi

logger = logging.getLogger(__name__)

class TokenDict(typing.TypedDict):
    DefinitionId: typing.Optional[str]
    NavigateToId: typing.Optional[str]
    Value: typing.Optional[str]
    Kind: int

def text(value, *, definition_id=None, navigate_to_id=None) -> typing.List[TokenDict]:
    return [
        {
            "DefinitionId": definition_id,
            "NavigateToId": navigate_to_id,
            "Value": value,
            "Kind": 0
        }
    ]

def newline() -> typing.List[TokenDict]:
    return [
        {
            "DefinitionId": None,
            "NavigateToId": None,
            "Value": None,
            "Kind": 1
        }
    ]

def whitespace(spaces=1) -> typing.List[TokenDict]:
    return [
        {
            "DefinitionId": None,
            "NavigateToId": None,
            "Value": ' ' * spaces,
            "Kind": 2
        }
    ]

def punctuation(value) -> typing.List[TokenDict]:
    return [
        {
            "DefinitionId": None,
            "NavigateToId": None,
            "Value": value,
            "Kind": 3
        }
    ]

def keyword(value, *, definition_id=None, navigate_to_id=None) -> typing.List[TokenDict]:
    return [
        {
            "DefinitionId": definition_id,
            "NavigateToId": navigate_to_id,
            "Value": value,
            "Kind": 4
        }
    ]

def typename(value, *, definition_id=None, navigate_to_id=None) -> typing.List[TokenDict]:
    return [
        {
            "DefinitionId": definition_id,
            "NavigateToId": navigate_to_id,
            "Value": value,
            "Kind": 6
        }
    ]

def member(value, *, definition_id=None, navigate_to_id=None) -> typing.List[TokenDict]:
    return [
        {
            "DefinitionId": definition_id,
            "NavigateToId": navigate_to_id,
            "Value": value,
            "Kind": 7
        }
    ]
    
def path_definition_id(path: openapi.Path) -> str:
    return f'path:{path.name}'

def model_definition_id(definition: typing.Union[str, openapi.Definition]) -> str:
    if isinstance(definition, str):
        return f'definition:{definition}'
    else:
        return f'definition:{definition.typename}'

class ApiViewNavigationEncoder:

    def serialize(self, document: openapi.Document):
        return [{
            "Text": document.file_path,
            "NavigationId": None,
            "ChildItems": [
                {
                    "Text": "Paths",
                    "NavigationId": None,
                    "DefinitionId": None,                
                    "ChildItems": [
                        {
                            "Text": path.name,
                            "NavigationId": path_definition_id(path),
                            "ChildItems": [],
                            "Tags": {
                                "TypeKind": "unknown"
                            }
                        } for path in document.paths
                    ],
                    "Tags": {
                        "TypeKind": "unknown"
                    }
                },
                {
                    "Text": "Models",
                    "NavigationId": None,
                    "DefinitionId": None,                
                    "ChildItems": [
                        {
                            "Text": definition.typename,
                            "NavigationId": model_definition_id(definition),
                            "ChildItems": [],
                            "Tags": {
                                "TypeKind": "unknown"
                            }
                        } for definition in document.definitions
                    ],
                    "Tags": {
                        "TypeKind": "unknown"
                    }
                }
            ],
            "Tags": {
                "TypeKind": "assembly"
            }
        }]

class ApiViewTokenEncoder:

    def serialize_operation_parameters(self, operation: openapi.Operation) -> typing.List[TokenDict]:
        tokens: typing.List[TokenDict] = []
        
        if operation.path_parameters:
            tokens += (
                keyword('path') +
                whitespace()
            )
            first = True
            for parameter in operation.path_parameters:
                if not first:
                    tokens += punctuation(',') + whitespace()
                    first = False
                tokens += (
                    member(parameter.name)
                )


        if operation.body_parameter:
            if tokens:
                tokens += punctuation(',') + whitespace()
            tokens += (
                keyword('body') +
                whitespace() +
                typename(operation.body_parameter.typename, navigate_to_id=model_definition_id(operation.body_parameter.typename))
            )

        for group, parameters in (('query', operation.query_parameters), ('header', operation.header_parameters)):
            if parameters:
                if tokens:
                    tokens += punctuation(',') + whitespace()
                first = True
                for parameter in parameters:
                    if not first:
                        tokens += punctuation(',') + whitespace()
                        first = False

                    tokens += (
                        keyword(group) +
                        whitespace() +
                        member(parameter.name)
                    )

        return tokens

    def serialize_operation(self, operation: openapi.Operation):
        tokens = (whitespace(2) +
                 keyword(operation.verb) + 
                 whitespace() + 
                 typename(operation.return_value.typename, definition_id=operation.return_value.typename) +
                 whitespace() + 
                 member(operation.name, definition_id=operation.name) + 
                 punctuation('(') +
                 self.serialize_operation_parameters(operation) +
                 punctuation(')') +
                 newline()
                 )
        return tokens

    def serialize_path(self, pathinstance: openapi.Path) -> typing.List[TokenDict]:
        tokens = text(pathinstance.name, definition_id=path_definition_id(pathinstance)) + newline()
        for operation in pathinstance.operations:
            tokens += self.serialize_operation(operation)
        return tokens

    def serialize_definition(self, definition:openapi.Definition) -> typing.List[TokenDict]:
        return (
            keyword("Model") + whitespace() + typename(definition.typename, definition_id=model_definition_id(definition)) + newline()
        )
        

    def serialize(self, document):
        tokens = []
        for pathinstance in document.paths:
            tokens += self.serialize_path(pathinstance)
        if tokens:
            tokens += newline() + newline()
        for definition in document.definitions:
            tokens += self.serialize_definition(definition)

        return tokens

class ApiViewEncoder(json.JSONEncoder):

    def __init__(self, *, navigation_encoder=ApiViewNavigationEncoder(), token_encoder=ApiViewTokenEncoder(), **kwargs):
        super().__init__(**kwargs)

        self.navigation_encoder = navigation_encoder
        self.token_encoder = token_encoder

    def default(self, o):
        if isinstance(o, openapi.Document):
            return {
                "Navigation": self.navigation_encoder.serialize(document=o),
                "Tokens": list(self.token_encoder.serialize(document=o))
            }
        else:
            return json.JSONEncoder.default(self, o)

if __name__ == '__main__':
    import sys
    logging.basicConfig()

    doc = openapi.Document(sys.argv[1])
    out = json.dumps(doc, cls=ApiViewEncoder, indent=2)
    print(out)