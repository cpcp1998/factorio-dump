import collections
import itertools
import platform
from pathlib import Path
from load import *
from prototype import *


class DataExtractor:
    def __init__(self, game_dir, mods_dir, difficulty):
        self.game_dir = game_dir
        self.mods_dir = mods_dir
        self.mod_manager = ModManager(game_dir, mods_dir)
        self.mod_settings = PropertyTree.load_mod_settings(os.path.join(mods_dir, 'mod-settings.dat'))
        self.lua_loader = LuaLoader(self.mod_manager, self.mod_settings)
        self.locale_provider = LocaleProvider('zh-CN', 'en', self.mod_manager)
        self.icon_loader = IconLoader(self.mod_manager)

        dataraw = self.lua_loader.get_dataraw()
        self.items = {}
        for t in ('item', 'ammo', 'capsule', 'gun', 'module', 'tool', 'armor', 'mining-tool', 'repair-tool', 'item-with-entity-data', 'rail-planner', 'item-with-label', 'item-with-inventory', 'item-with-tags'):
            for i in dataraw[t]:
                self.items[i] = Item(dataraw[t][i], self.icon_loader)
        self.fluids = {f: Fluid(dataraw['fluid'][f], self.icon_loader) for f in dataraw['fluid']}
        self.techs = {t: Technology(dataraw['technology'][t], self.icon_loader, difficulty) for t in dataraw['technology']}
        self.item_groups = {g: ItemGroup(dataraw['item-group'][g], self.icon_loader) for g in dataraw['item-group']}
        self.item_subgroups = {g: ItemSubGroup(dataraw['item-subgroup'][g]) for g in dataraw['item-subgroup']}
        self.recipes = {r: Recipe(dataraw['recipe'][r], self.icon_loader, difficulty, self.items, self.fluids) for r in dataraw['recipe']}
        self.resources = {}
        for r in dataraw['resource']:
            self.resources[r] = Resource(dataraw['resource'][r], self.icon_loader, self.fluids)
        self.mining_drills = {}
        for d in dataraw['mining-drill']:
            self.mining_drills[d] = MiningDrill(dataraw['mining-drill'][d], self.icon_loader)
        self.crafting_machines = {}
        for t in ('assembling-machine', 'rocket-silo', 'furnace'):
            for e in dataraw[t]:
                self.crafting_machines[e] = CraftingMachine(dataraw[t][e], self.icon_loader)
        self.offshore_pumps = {}
        for p in dataraw['offshore-pump']:
            self.offshore_pumps[p] = OffshorePump(dataraw['offshore-pump'][p], self.icon_loader)
        self.modules = {}
        for m in dataraw['module']:
            self.modules[m] = Module(dataraw['module'][m], self.icon_loader)

    def resolve_fluid_temperature(self):
        for fluid in self.fluids.values():
            fluid.available_temperatures = set()
        for recipe in self.recipes.values():
            for product in recipe.results:
                if product.type == 'fluid':
                    fluid = self.fluids[product.name]
                    fluid.available_temperatures.add(product.temperature)
        for fluid in self.fluids.values():
            fluid.temperature_groups = [fluid.available_temperatures]
        for recipe in self.recipes.values():
            for ingredient in recipe.ingredients:
                if ingredient.type == 'fluid':
                    fluid = self.fluids[ingredient.name]
                    min_temp = ingredient.minimum_temperature
                    max_temp = ingredient.maximum_temperature
                    new_groups = []
                    for group in fluid.temperature_groups:
                        satisfied = set()
                        unsatisfied = set()
                        for temp in group:
                            if min_temp <= temp <= max_temp:
                                satisfied.add(temp)
                            else:
                                unsatisfied.add(temp)
                        if satisfied:
                            new_groups.append(satisfied)
                        if unsatisfied:
                            new_groups.append(unsatisfied)
                    if not new_groups:
                        new_groups = [set()]
                    fluid.temperature_groups = new_groups

    def get_material_list(self):
        result = {}
        for item in self.items.values():
            name = item.name
            subgroup = item.subgroup
            group = self.item_subgroups[subgroup].group
            if group not in result:
                result[group] = {}
            if subgroup not in result[group]:
                result[group][subgroup] = []
            result[group][subgroup].append('item/'+name)
        for fluid in self.fluids.values():
            name = fluid.name
            subgroup = fluid.subgroup
            group = self.item_subgroups[subgroup].group
            if group not in result:
                result[group] = {}
            if subgroup not in result[group]:
                result[group][subgroup] = []
            result[group][subgroup].append('fluid/'+name)
        for group in result:
            subgroups = list(result[group])
            subgroups.sort(key=lambda s: self.item_subgroups[s])
            ordered_subgroup = []
            for subgroup in subgroups:
                materials = result[group][subgroup]
                materials.sort(key=lambda s: self.items[s[5:]] if s.startswith('item/') else self.fluids[s[6:]])
                ordered_subgroup.append(materials)
            result[group] = ordered_subgroup
        group_order = list(result)
        group_order.sort(key=lambda s: self.item_groups[s])
        result = {'group/'+k: v for k, v in result.items()}
        group_order = ['group/'+i for i in group_order]
        return group_order, result

    def get_recipe_list(self):
        result = {}
        for recipe in self.recipes.values():
            name = recipe.name
            subgroup = recipe.subgroup
            group = self.item_subgroups[subgroup].group
            if group not in result:
                result[group] = {}
            if subgroup not in result[group]:
                result[group][subgroup] = []
            result[group][subgroup].append(name)
        for group in result:
            subgroups = list(result[group])
            subgroups.sort(key=lambda s: self.item_subgroups[s])
            ordered_subgroup = []
            for subgroup in subgroups:
                recipes = result[group][subgroup]
                recipes.sort(key=lambda s: self.recipes[s])
                ordered_subgroup.append(['recipe/'+r for r in recipes])
            result[group] = ordered_subgroup
        group_order = list(result)
        group_order.sort(key=lambda s: self.item_groups[s])
        result = {'group/'+k: v for k, v in result.items()}
        group_order = ['group/'+i for i in group_order]
        return group_order, result

    def get_resource_list(self):
        resources = list(self.resources)
        resources.sort(key=lambda s: self.resources[s])
        resources = ['resource/'+r for r in resources]
        return resources

    def get_module_list(self):
        modules = list(self.modules)
        modules.sort(key=lambda s: self.modules[s])
        modules = ['item/'+i for i in modules]
        return modules

    def get_machine_list(self):
        result = {}
        for m in self.crafting_machines.values():
            for c in m.categories:
                c = 'crafting/' + c
                if c not in result:
                    result[c] = []
                result[c].append(m.name)
        for m in self.mining_drills.values():
            for c in m.categories:
                c = 'mining/' + c
                if c not in result:
                    result[c] = []
                result[c].append(m.name)
        for c in result:
            if c.startswith('crafting'):
                result[c].sort(key=lambda s: (-self.crafting_machines[s].module_slots,
                                              -self.crafting_machines[s].speed,
                                              self.crafting_machines[s]))
            else:
                result[c].sort(key=lambda s: (-self.mining_drills[s].module_slots,
                                              -self.mining_drills[s].speed,
                                              self.mining_drills[s]))
            result[c] = ['entity/'+i for i in result[c]]
        return result

    def get_order_info(self):
        result = {}
        material_groups, materials = self.get_material_list()
        recipe_groups, recipes = self.get_recipe_list()
        result['material_group'] = material_groups
        result['recipe_group'] = recipe_groups
        result['material'] = materials
        result['recipe'] = recipes
        result['resource'] = self.get_resource_list()
        result['module'] = self.get_module_list()
        result['machine'] = self.get_machine_list()
        return result

    def get_free_fluids(self):
        return ['fluid/'+p.fluid for p in self.offshore_pumps.values()]

    def get_raw_unlockable_recipes(self):
        result = set(recipe.name for recipe in self.recipes.values() if recipe.enabled)

        researchable_techs = set()
        changed = True
        while changed:
            changed = False
            for tech in self.techs.values():
                if tech.name not in researchable_techs and tech.enabled:
                    if researchable_techs.issuperset(tech.prerequisites):
                        changed = True
                        researchable_techs.add(tech.name)
        for tech in researchable_techs:
            tech = self.techs[tech]
            result = result.union(tech.unlocks)

        return list(result)

    def get_unlockable_recipes(self):
        return ['recipe/'+i for i in self.get_raw_unlockable_recipes()] + self.get_resource_list()

    def get_icons(self):
        group_icons, group_icon_mapping = ItemGroup.get_atlas()
        tech_icons, tech_icon_mapping = Technology.get_atlas()
        group_icon_mapping = {'group/'+k: v for k, v in group_icon_mapping.items()}
        tech_icon_mapping = {'technology/'+k: v for k, v in tech_icon_mapping.items()}
        small_icons = {'item/'+i: icon for i, icon in Item.icons.items()}
        small_icons.update({'fluid/'+i: icon for i, icon in Fluid.icons.items()})
        small_icons.update({'resource/'+i: icon for i, icon in Resource.icons.items()})
        small_icons.update({'recipe/'+i: icon for i, icon in Recipe.icons.items()})
        small_icons.update({'entity/'+i: icon for i, icon in Entity.icons.items()})
        small_icons, small_icon_mapping = IconLoader.get_atlas(small_icons, 32)
        return group_icons, tech_icons, small_icons,\
            {"group": group_icon_mapping, "tech": tech_icon_mapping, "small": small_icon_mapping}

    def get_localised_names(self):
        result = {'item/'+i.name: i.get_localised_name(self.locale_provider) for i in self.items.values()}
        result.update({'fluid/' + i.name: i.get_localised_name(self.locale_provider) for i in self.fluids.values()})
        result.update({'resource/' + i.name: i.get_localised_name(self.locale_provider) for i in self.resources.values()})
        result.update({'recipe/' + i.name: i.get_localised_name(self.locale_provider) for i in self.recipes.values()})
        result.update({'entity/' + i.name: i.get_localised_name(self.locale_provider) for i in self.crafting_machines.values()})
        result.update({'entity/' + i.name: i.get_localised_name(self.locale_provider) for i in self.mining_drills.values()})
        result.update({'entity/' + i.name: i.get_localised_name(self.locale_provider) for i in self.offshore_pumps.values()})
        result.update({'technology/' + i.name: i.get_localised_name(self.locale_provider) for i in self.techs.values()})
        result.update({'group/' + i.name: i.get_localised_name(self.locale_provider) for i in self.item_groups.values()})
        return result

    def get_machine_attr(self):
        result = {}
        for machine in self.crafting_machines.values():
            attribute = {}
            name = 'entity/'+machine.name
            attribute['name'] = name
            attribute['speed'] = machine.speed
            attribute['module'] = machine.module_slots
            attribute['effects'] = machine.allowed_effects
            attribute['in'] = machine.ingredient_count
            attribute['in_fluid'] = machine.input_fluid_box
            attribute['out_fluid'] = machine.output_fluid_box
            attribute['fixed'] = 'recipe/'+machine.fixed_recipe if machine.fixed_recipe else machine.fixed_recipe
            attribute['base_prod'] = machine.base_productivity
            result[name] = attribute
        for machine in self.mining_drills.values():
            attribute = {}
            name = 'entity/'+machine.name
            attribute['name'] = name
            attribute['speed'] = machine.speed
            attribute['module'] = machine.module_slots
            attribute['effects'] = machine.allowed_effects
            attribute['in'] = 1
            attribute['in_fluid'] = machine.input_fluid_box
            attribute['out_fluid'] = machine.output_fluid_box
            attribute['fixed'] = ''
            attribute['base_prod'] = machine.base_productivity
            result[name] = attribute
        return result

    def get_module_attr(self):
        result = {}
        for module in self.modules.values():
            attribute = {}
            name = 'item/'+module.name
            attribute['name'] = name
            effects = {}
            for e in ("speed", "productivity", "consumption", "pollution"):
                effects[e] = module.effects[e]
            attribute['effects'] = effects
            if len(module.limitation) > 0:
                attribute['limitation'] = ['recipe/'+i for i in module.limitation] + self.get_resource_list()
            else:
                attribute['limitation'] = []
            result[name] = attribute
        return result

    def get_temperature_attr(self):
        result = {}
        for fluid in self.fluids.values():
            name = 'fluid/'+fluid.name
            if len(fluid.temperature_groups) > 1:
                attribute = fluid.temperature_groups
                attribute = [list(s) for s in attribute]
                for s in attribute:
                    s.sort()
                attribute.sort(key=lambda s: min(s))
                result[name] = attribute
        return result

    def get_recipe_attr(self):
        def order(material):
            temp = 0
            if '@' in material:
                temp = material.split('@')[1]
                material = material.split('@')[0]
            type_ = material.split('/')[0]
            name_ = material.split('/')[1]
            if type_ == 'resource':
                resource = self.resources[name_]
                return '', '', '', '', resource.order, resource.name, 0
            else:
                if type_ == 'item':
                    item = self.items[name_]
                else:
                    item = self.fluids[name_]
                subgroup = self.item_subgroups[item.subgroup]
                group = self.item_groups[subgroup.group]
                return group.order_in_recipe, group.name, subgroup.order, subgroup.name, item.order, item.name, temp

        temperature_attr = self.get_temperature_attr()
        result = {}
        for recipe in self.recipes.values():
            attribute = {}
            name = 'recipe/'+recipe.name
            category = 'crafting/'+recipe.category
            time = recipe.energy_required
            products = {}
            for product in recipe.results:
                product_name = product.type+'/'+product.name
                if product_name in temperature_attr:
                    number = -1
                    for i, temps in enumerate(temperature_attr[product_name]):
                        if product.temperature in temps:
                            number = i
                    assert number != -1
                    product_name = product_name+'@'+str(number)
                if product_name not in products:
                    products[product_name] = 0
                assert product.amount is not None, product_name
                products[product_name] += product.amount
            products = [(k, v) for k, v in products.items()]
            products.sort(key=lambda s: order(s[0]))
            ingredients = []
            for ingredient in recipe.ingredients:
                ingredient_name = ingredient.type+'/'+ingredient.name
                if ingredient_name in temperature_attr:
                    numbers = []
                    for i, temps in enumerate(temperature_attr[ingredient_name]):
                        if len(temps) == 0 or ingredient.minimum_temperature <= temps[0] <= ingredient.maximum_temperature:
                            numbers.append(i)
                    ingredients.append([(ingredient_name+'@'+str(i), ingredient.amount) for i in numbers])
                else:
                    ingredients.append([(ingredient_name, ingredient.amount)])
            ingredients.sort(key=lambda s: order(s[0][0]))
            ingredients = itertools.product(*ingredients)
            ingredients = [list(i) for i in ingredients]
            attribute['name'] = name
            attribute['category'] = category
            attribute['time'] = time
            attribute['products'] = products
            attribute['ingredients'] = ingredients
            result[name] = attribute
        for resource in self.resources.values():
            attribute = {}
            name = 'resource/'+resource.name
            category = 'mining/'+resource.category
            time = resource.mining_time
            products = {}
            for product in resource.results:
                product_name = product.type + '/' + product.name
                if product_name in temperature_attr:
                    number = -1
                    for i, temps in enumerate(temperature_attr[product_name]):
                        if product.temperature in temps:
                            number = i
                    assert number != -1
                    product_name = product_name + '@' + str(number)
                if product_name not in products:
                    products[product_name] = 0
                assert product.amount is not None, product_name
                products[product_name] += product.amount
            products = [(k, v) for k, v in products.items()]
            products.sort(key=lambda s: order(s[0]))
            ingredients = [[(name, 1)]]
            if resource.fluid_amount > 0:
                ingredient_name = 'fluid/' + resource.required_fluid
                if ingredient_name in temperature_attr:
                    numbers = range(len(temperature_attr[ingredient_name]))
                    ingredients.append([(ingredient_name+'@'+str(i), resource.fluid_amount) for i in numbers])
                else:
                    ingredients.append([(ingredient_name, resource.fluid_amount)])
            ingredients = itertools.product(*ingredients)
            ingredients = [list(i) for i in ingredients]
            attribute['name'] = name
            attribute['category'] = category
            attribute['time'] = time
            attribute['products'] = products
            attribute['ingredients'] = ingredients
            result[name] = attribute
        return result

    def generate(self):
        result = {}
        self.resolve_fluid_temperature()
        result['order_info'] = self.get_order_info()
        result['free_fluids'] = self.get_free_fluids()
        result['unlockable_recipes'] = self.get_unlockable_recipes()
        group_icons, tech_icons, small_icons, icon_mapping = self.get_icons()
        result['icon_mapping'] = icon_mapping
        result['localised_names'] = self.get_localised_names()
        result['machine_attr'] = self.get_machine_attr()
        result['module_attr'] = self.get_module_attr()
        result['temperature_attr'] = self.get_temperature_attr()
        result['recipe_attr'] = self.get_recipe_attr()
        return group_icons, tech_icons, small_icons, result

    @staticmethod
    def check_dump(n):
        assert n is not None
        if type(n) == dict:
            for k, v in n.items():
                assert type(k) == str
                DataExtractor.check_dump(v)
        elif type(n) == list:
            for v in n:
                DataExtractor.check_dump(v)
        elif type(n) == tuple:
            for v in n:
                DataExtractor.check_dump(v)
        else:
            assert type(n) == bool or type(n) == str or type(n) == int or type(n) == float, type(n)

    def generate_and_dump(self, dir):
        group_icons, tech_icons, small_icons, result = self.generate()
        DataExtractor.check_dump(result)
        os.makedirs(dir, exist_ok=True)
        with open(os.path.join(dir, 'info.json'), 'w', encoding='utf-8') as f:
            json.dump(result, f, indent=2)
        group_icons.save(os.path.join(dir, 'group.png'))
        tech_icons.save(os.path.join(dir, 'tech.png'))
        small_icons.save(os.path.join(dir, 'small.png'))


if __name__ == '__main__':
    operating_system = platform.system()
    if operating_system == 'Windows':
        program_files = os.getenv('PROGRAMFILES(x86)')
        appdata = os.getenv('APPDATA')
        game_dir = os.path.join(program_files, 'Steam', 'steamapps', 'common', 'factorio')
        mods_dir = os.path.join(appdata, 'factorio', 'mods')
    elif operating_system == 'Darwin':
        home = str(Path.home())
        game_dir = os.path.join(home, 'Library', 'Application Support', 'Steam', 'steamapps', 'common', 'Factorio', 'factorio.app', 'Contents')
        mods_dir = os.path.join(home, 'Library', 'Application Support', 'factorio', 'mods')
    data_extractor = DataExtractor(game_dir, mods_dir, 'normal')
    data_extractor.generate_and_dump('data')
