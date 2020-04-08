import json
import logging
import typing

import openapi

logger = logging.getLogger(__name__)

if typing.TYPE_CHECKING:
    from openapi import ModelProperty

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
            "Kind": 0,
        }
    ]


def newline() -> typing.List[TokenDict]:
    return [{"DefinitionId": None, "NavigateToId": None, "Value": None, "Kind": 1}]


def whitespace(spaces=1) -> typing.List[TokenDict]:
    return [
        {"DefinitionId": None, "NavigateToId": None, "Value": " " * spaces, "Kind": 2}
    ]


def punctuation(value) -> typing.List[TokenDict]:
    return [{"DefinitionId": None, "NavigateToId": None, "Value": value, "Kind": 3}]


def keyword(
    value, *, definition_id=None, navigate_to_id=None
) -> typing.List[TokenDict]:
    return [
        {
            "DefinitionId": definition_id,
            "NavigateToId": navigate_to_id,
            "Value": value,
            "Kind": 4,
        }
    ]


def typename(
    value, *, definition_id=None, navigate_to_id=None
) -> typing.List[TokenDict]:
    return [
        {
            "DefinitionId": definition_id,
            "NavigateToId": navigate_to_id,
            "Value": value,
            "Kind": 6,
        }
    ]


def member(value, *, definition_id=None, navigate_to_id=None) -> typing.List[TokenDict]:
    return [
        {
            "DefinitionId": definition_id,
            "NavigateToId": navigate_to_id,
            "Value": value,
            "Kind": 7,
        }
    ]


def path_definition_id(path: openapi.Path) -> str:
    return f"path:{path.name}"


def model_definition_id(definition: typing.Union[str, openapi.Definition]) -> str:
    if isinstance(definition, str):
        return f"definition:{definition}"
    else:
        return f"definition:{definition.typename}"


class ApiViewNavigationEncoder:
    def serialize(self, document: openapi.Document):
        return [
            {
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
                                "Tags": {"TypeKind": "unknown"},
                            }
                            for path in document.paths
                        ],
                        "Tags": {"TypeKind": "unknown"},
                    },
                    {
                        "Text": "Resources",
                        "NavigationId": None,
                        "DefinitionId": None,
                        "ChildItems": [
                            {
                                "Text": definition.typename,
                                "NavigationId": model_definition_id(definition),
                                "ChildItems": [],
                                "Tags": {"TypeKind": "unknown"},
                            }
                            for definition in document.resourcedefinitions
                        ],
                        "Tags": {"TypeKind": "unknown"},
                    },
                    {
                        "Text": "Supporting models",
                        "NavigationId": None,
                        "DefinitionId": None,
                        "ChildItems": [
                            {
                                "Text": definition.typename,
                                "NavigationId": model_definition_id(definition),
                                "ChildItems": [],
                                "Tags": {"TypeKind": "unknown"},
                            }
                            for definition in document.supportdefinitions
                        ],
                        "Tags": {"TypeKind": "unknown"},
                    },
                ],
                "Tags": {"TypeKind": "assembly"},
            }
        ]


class ApiViewTokenEncoder:
    def serialize_operation_parameters(
        self, operation: openapi.Operation
    ) -> typing.List[TokenDict]:
        tokens: typing.List[TokenDict] = []

        if operation.path_parameters:
            tokens += keyword("path") + whitespace()
            first = True
            for parameter in operation.path_parameters:
                if not first:
                    tokens += punctuation(",") + whitespace()
                tokens += member(parameter.name)
                first = False

        if operation.body_parameter:
            if tokens:
                tokens += punctuation(",") + whitespace()
            tokens += (
                keyword("body")
                + whitespace()
                + typename(
                    operation.body_parameter.typename,
                    navigate_to_id=model_definition_id(
                        operation.body_parameter.typename
                    ),
                )
            )

        for group, parameters in (
            ("query", operation.query_parameters),
            ("header", operation.header_parameters),
        ):
            if parameters:
                if tokens:
                    tokens += punctuation(",") + whitespace()
                first = True
                tokens += keyword(group) + whitespace()
                for parameter in parameters:
                    if not first:
                        tokens += punctuation(",") + whitespace()

                    tokens += member(parameter.name)
                    first = False

        return tokens

    def serialize_operation(self, operation: openapi.Operation):
        tokens = (
            whitespace(2)
            + keyword(operation.verb)
            + whitespace()
            + typename(
                operation.return_value.typename,
                definition_id=operation.return_value.typename,
            )
            + whitespace()
            + member(operation.name, definition_id=operation.name)
            + punctuation("(")
            + self.serialize_operation_parameters(operation)
            + punctuation(")")
            + newline()
        )
        return tokens

    def serialize_path(self, pathinstance: openapi.Path) -> typing.List[TokenDict]:
        tokens = (
            text(pathinstance.name, definition_id=path_definition_id(pathinstance))
            + newline()
        )
        for operation in pathinstance.operations:
            tokens += self.serialize_operation(operation)
        return tokens

    def _recurse_serialize_definition(
        self, modelproperty: "ModelProperty", *, depth=1
    ) -> typing.List[TokenDict]:
        tokens = []
        propertytypename = modelproperty.itemtypename or modelproperty.typename
        if modelproperty.typetype == "model":
            propertytypetoken = typename(
                propertytypename, navigate_to_id=model_definition_id(propertytypename)
            )
        else:
            propertytypetoken = keyword(propertytypename)

        if modelproperty.itemtypename:
            propertytypetoken = punctuation("[") + propertytypetoken + punctuation("]")

        tokens += (
            whitespace(4 * depth)
            + propertytypetoken
            + whitespace(1)
            + member(modelproperty.name)
            + newline()
        )
        for childproperty in modelproperty.properties:
            tokens += self._recurse_serialize_definition(childproperty, depth=depth + 1)

        return tokens

    def serialize_definition(
        self, resource_or_support: str, definition: openapi.Definition
    ) -> typing.List[TokenDict]:
        tokens = (
            keyword(resource_or_support)
            + whitespace()
            + typename(
                definition.typename, definition_id=model_definition_id(definition)
            )
        )
        bases: typing.List[TokenDict] = []
        for base in definition.bases:
            if not bases:
                bases += punctuation("(")
            bases += typename(
                base.typename, navigate_to_id=model_definition_id(base.typename)
            )
        if bases:
            tokens = tokens + bases + punctuation(")")
        tokens = tokens + newline()
        for modelproperty in definition.properties:
            tokens += self._recurse_serialize_definition(modelproperty)
        return tokens

    def serialize(self, document):
        tokens = []
        for pathinstance in document.paths:
            tokens += self.serialize_path(pathinstance)
        if tokens:
            tokens += newline() + newline()
        for definition in document.resourcedefinitions:
            tokens += self.serialize_definition("ResourceModel", definition)
        for definition in document.supportdefinitions:
            tokens += self.serialize_definition("InnerModel", definition)

        return tokens


class ApiViewEncoder(json.JSONEncoder):
    def __init__(
        self,
        *,
        navigation_encoder=ApiViewNavigationEncoder(),
        token_encoder=ApiViewTokenEncoder(),
        **kwargs,
    ):
        super().__init__(**kwargs)

        self.navigation_encoder = navigation_encoder
        self.token_encoder = token_encoder

    def default(self, o):
        if isinstance(o, openapi.Document):
            return {
                "Navigation": self.navigation_encoder.serialize(document=o),
                "Tokens": list(self.token_encoder.serialize(document=o)),
            }
        else:
            return json.JSONEncoder.default(self, o)


def cli():
    import argparse

    parser = argparse.ArgumentParser("apiserializer")
    parser.add_argument(type=str, dest="filename")
    parser.add_argument("--debug", action="store_true", dest="debug", default=False)
    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.debug else logging.WARN)
    doc = openapi.Document(args.filename)
    out = json.dumps(doc, cls=ApiViewEncoder, indent=2)
    print(out)


if __name__ == "__main__":
    cli()
