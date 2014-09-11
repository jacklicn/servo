# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.

from WebIDL import IDLInterface

autogenerated_comment = "/* THIS FILE IS AUTOGENERATED - DO NOT EDIT */\n"

class Configuration:
    """
    Represents global configuration state based on IDL parse data and
    the configuration file.
    """
    def __init__(self, filename, parseData):
        # Read the configuration file.
        glbl = {}
        execfile(filename, glbl)
        config = glbl['DOMInterfaces']

        # Build descriptors for all the interfaces we have in the parse data.
        # This allows callers to specify a subset of interfaces by filtering
        # |parseData|.
        self.descriptors = []
        self.interfaces = {}
        self.maxProtoChainLength = 0;
        for thing in parseData:
            # Some toplevel things are sadly types, and those have an
            # isInterface that doesn't mean the same thing as IDLObject's
            # isInterface()...
            if not isinstance(thing, IDLInterface):
                continue

            iface = thing
            self.interfaces[iface.identifier.name] = iface
            if iface.identifier.name not in config:
                # Completely skip consequential interfaces with no descriptor
                # if they have no interface object because chances are we
                # don't need to do anything interesting with them.
                if iface.isConsequential() and not iface.hasInterfaceObject():
                    continue
                entry = {}
            else:
                entry = config[iface.identifier.name]
            if not isinstance(entry, list):
                assert isinstance(entry, dict)
                entry = [entry]
            self.descriptors.extend([Descriptor(self, iface, x) for x in entry])

        # Mark the descriptors for which only a single nativeType implements
        # an interface.
        for descriptor in self.descriptors:
            intefaceName = descriptor.interface.identifier.name
            otherDescriptors = [d for d in self.descriptors
                                if d.interface.identifier.name == intefaceName]
            descriptor.uniqueImplementation = len(otherDescriptors) == 1

        self.enums = [e for e in parseData if e.isEnum()]
        self.dictionaries = [d for d in parseData if d.isDictionary()]
        self.callbacks = [c for c in parseData if
                          c.isCallback() and not c.isInterface()]

        # Keep the descriptor list sorted for determinism.
        self.descriptors.sort(lambda x,y: cmp(x.name, y.name))

    def getInterface(self, ifname):
        return self.interfaces[ifname]
    def getDescriptors(self, **filters):
        """Gets the descriptors that match the given filters."""
        curr = self.descriptors
        for key, val in filters.iteritems():
            if key == 'webIDLFile':
                getter = lambda x: x.interface.filename()
            elif key == 'hasInterfaceObject':
                getter = lambda x: x.interface.hasInterfaceObject()
            elif key == 'isCallback':
                getter = lambda x: x.interface.isCallback()
            elif key == 'isJSImplemented':
                getter = lambda x: x.interface.isJSImplemented()
            else:
                getter = lambda x: getattr(x, key)
            curr = filter(lambda x: getter(x) == val, curr)
        return curr
    def getEnums(self, webIDLFile):
        return filter(lambda e: e.filename() == webIDLFile, self.enums)

    @staticmethod
    def _filterForFile(items, webIDLFile=""):
        """Gets the items that match the given filters."""
        if not webIDLFile:
            return items

        return filter(lambda x: x.filename() == webIDLFile, items)

    def getDictionaries(self, webIDLFile=""):
        return self._filterForFile(self.dictionaries, webIDLFile=webIDLFile)
    def getCallbacks(self, webIDLFile=""):
        return self._filterForFile(self.callbacks, webIDLFile=webIDLFile)

    def getDescriptor(self, interfaceName):
        """
        Gets the appropriate descriptor for the given interface name.
        """
        iface = self.getInterface(interfaceName)
        descriptors = self.getDescriptors(interface=iface)

        # We should have exactly one result.
        if len(descriptors) is not 1:
            raise NoSuchDescriptorError("For " + interfaceName + " found " +
                                        str(len(matches)) + " matches");
        return descriptors[0]
    def getDescriptorProvider(self):
        """
        Gets a descriptor provider that can provide descriptors as needed.
        """
        return DescriptorProvider(self)

class NoSuchDescriptorError(TypeError):
    def __init__(self, str):
        TypeError.__init__(self, str)

class DescriptorProvider:
    """
    A way of getting descriptors for interface names
    """
    def __init__(self, config):
        self.config = config

    def getDescriptor(self, interfaceName):
        """
        Gets the appropriate descriptor for the given interface name given the
        context of the current descriptor.
        """
        return self.config.getDescriptor(interfaceName)

class Descriptor(DescriptorProvider):
    """
    Represents a single descriptor for an interface. See Bindings.conf.
    """
    def __init__(self, config, interface, desc):
        DescriptorProvider.__init__(self, config)
        self.interface = interface

        # Read the desc, and fill in the relevant defaults.
        ifaceName = self.interface.identifier.name

        # Callback types do not use JS smart pointers, so we should not use the
        # built-in rooting mechanisms for them.
        if self.interface.isCallback():
            self.needsRooting = False
        else:
            self.needsRooting = True

        self.returnType = desc.get('returnType', "Temporary<%s>" % ifaceName)
        self.argumentType = "JSRef<%s>" % ifaceName
        self.memberType = "Root<'a, 'b, %s>" % ifaceName
        self.nativeType = desc.get('nativeType', 'JS<%s>' % ifaceName)
        self.concreteType = desc.get('concreteType', ifaceName)
        self.register = desc.get('register', True)
        self.outerObjectHook = desc.get('outerObjectHook', 'None')

        # If we're concrete, we need to crawl our ancestor interfaces and mark
        # them as having a concrete descendant.
        self.concrete = desc.get('concrete', True)
        if self.concrete:
            self.proxy = False
            operations = {
                'IndexedGetter': None,
                'IndexedSetter': None,
                'IndexedCreator': None,
                'IndexedDeleter': None,
                'NamedGetter': None,
                'NamedSetter': None,
                'NamedCreator': None,
                'NamedDeleter': None,
                'Stringifier': None
            }
            iface = self.interface
            while iface:
                for m in iface.members:
                    if not m.isMethod():
                        continue

                    def addOperation(operation, m):
                        if not operations[operation]:
                            operations[operation] = m
                    def addIndexedOrNamedOperation(operation, m):
                        self.proxy = True
                        if m.isIndexed():
                            operation = 'Indexed' + operation
                        else:
                            assert m.isNamed()
                            operation = 'Named' + operation
                        addOperation(operation, m)
                        
                    if m.isStringifier():
                        addOperation('Stringifier', m)
                    else:
                        if m.isGetter():
                            addIndexedOrNamedOperation('Getter', m)
                        if m.isSetter():
                            addIndexedOrNamedOperation('Setter', m)
                        if m.isCreator():
                            addIndexedOrNamedOperation('Creator', m)
                        if m.isDeleter():
                            addIndexedOrNamedOperation('Deleter', m)
                            raise TypeError("deleter specified on %s but we "
                                            "don't support deleters yet" %
                                            self.interface.identifier.name)

                iface.setUserData('hasConcreteDescendant', True)
                iface = iface.parent

            if self.proxy:
                self.operations = operations
                iface = self.interface
                while iface:
                    iface.setUserData('hasProxyDescendant', True)
                    iface = iface.parent

        self.name = interface.identifier.name

        # self.extendedAttributes is a dict of dicts, keyed on
        # all/getterOnly/setterOnly and then on member name. Values are an
        # array of extended attributes.
        self.extendedAttributes = { 'all': {}, 'getterOnly': {}, 'setterOnly': {} }

        def addExtendedAttribute(attribute, config):
            def add(key, members, attribute):
                for member in members:
                    self.extendedAttributes[key].setdefault(member, []).append(attribute)

            if isinstance(config, dict):
                for key in ['all', 'getterOnly', 'setterOnly']:
                    add(key, config.get(key, []), attribute)
            elif isinstance(config, list):
                add('all', config, attribute)
            else:
                assert isinstance(config, str)
                if config == '*':
                    iface = self.interface
                    while iface:
                        add('all', map(lambda m: m.name, iface.members), attribute)
                        iface = iface.parent
                else:
                    add('all', [config], attribute)

        # Build the prototype chain.
        self.prototypeChain = []
        parent = interface
        while parent:
            self.prototypeChain.insert(0, parent.identifier.name)
            parent = parent.parent
        config.maxProtoChainLength = max(config.maxProtoChainLength,
                                         len(self.prototypeChain))

    def getExtendedAttributes(self, member, getter=False, setter=False):
        def maybeAppendInfallibleToAttrs(attrs, throws):
            if throws is None:
                attrs.append("infallible")
            elif throws is True:
                pass
            else:
                raise TypeError("Unknown value for 'Throws'")

        name = member.identifier.name
        if member.isMethod():
            attrs = self.extendedAttributes['all'].get(name, [])
            throws = member.getExtendedAttribute("Throws")
            maybeAppendInfallibleToAttrs(attrs, throws)
            return attrs

        assert member.isAttr()
        assert bool(getter) != bool(setter)
        key = 'getterOnly' if getter else 'setterOnly'
        attrs = self.extendedAttributes['all'].get(name, []) + self.extendedAttributes[key].get(name, [])
        throws = member.getExtendedAttribute("Throws")
        if throws is None:
            throwsAttr = "GetterThrows" if getter else "SetterThrows"
            throws = member.getExtendedAttribute(throwsAttr)
        maybeAppendInfallibleToAttrs(attrs, throws)
        return attrs

    def isGlobal(self):
        """
        Returns true if this is the primary interface for a global object
        of some sort.
        """
        return (self.interface.getExtendedAttribute("Global") or
                self.interface.getExtendedAttribute("PrimaryGlobal"))


# Some utility methods
def getTypesFromDescriptor(descriptor):
    """
    Get all argument and return types for all members of the descriptor
    """
    members = [m for m in descriptor.interface.members]
    if descriptor.interface.ctor():
        members.append(descriptor.interface.ctor())
    members.extend(descriptor.interface.namedConstructors)
    signatures = [s for m in members if m.isMethod() for s in m.signatures()]
    types = []
    for s in signatures:
        assert len(s) == 2
        (returnType, arguments) = s
        types.append(returnType)
        types.extend(a.type for a in arguments)

    types.extend(a.type for a in members if a.isAttr())
    return types

def getFlatTypes(types):
    retval = set()
    for type in types:
        type = type.unroll()
        if type.isUnion():
            retval |= set(type.flatMemberTypes)
        else:
            retval.add(type)
    return retval

def getTypesFromDictionary(dictionary):
    """
    Get all member types for this dictionary
    """
    types = []
    curDict = dictionary
    while curDict:
        types.extend([m.type for m in curDict.members])
        curDict = curDict.parent
    return types

def getTypesFromCallback(callback):
    """
    Get the types this callback depends on: its return type and the
    types of its arguments.
    """
    sig = callback.signatures()[0]
    types = [sig[0]] # Return type
    types.extend(arg.type for arg in sig[1]) # Arguments
    return types