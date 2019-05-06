"""
Modify the original file to make the class support feature extraction
"""
import torch
import torch.nn as nn
from torch.nn.parameter import Parameter
import torch.nn.functional as F
import math
import torch.utils.model_zoo as model_zoo
from ..modules import *

model_urls = {
    'resnet18': 'https://download.pytorch.org/models/resnet18-5c106cde.pth',
    'resnet34': 'https://download.pytorch.org/models/resnet34-333f7ec4.pth',
    'resnet50': 'https://download.pytorch.org/models/resnet50-19c8e357.pth',
    'resnet101': 'https://download.pytorch.org/models/resnet101-5d3b4d8f.pth',
    'resnet152': 'https://download.pytorch.org/models/resnet152-b121ed2d.pth',
}

__all__ = ["km_resnet50_3d_v2_0init_tem_reciprocal16"]

class KernelMask(nn.Module):
    """Softmax
    """
    def __init__(self, planes, temperature=1, init="zeros", std=0.01):
        super(KernelMask, self).__init__()
        assert(init in ("zeros", "ones", "normal")), "Invalid init method"
        self.temperature = temperature
        self.mask = Parameter(torch.zeros(planes, 1, 3, 1, 1))
        if init == "ones":
            nn.init.constant_(self.mask, 1)
        elif init == "normal":
            nn.init.normal_(self.mask, mean=0, std=std)
        self.softmax = nn.Softmax(dim=2)

    def forward(self):
        return 3 * self.softmax(self.mask/self.temperature)

class KMBottleneck3D_v1(nn.Module):
    expansion = 4

    def __init__(self, inplanes, planes, 
                temperature=1/16, ratio=0.5, 
                stride=1, t_stride=1, downsample=None):
        super(KMBottleneck3D_v1, self).__init__()
        assert(ratio<=1 and ratio>=0), "Value of ratio must between 0 and 1."
        self.ratio = ratio
        t_channels = int(planes*ratio)
        p_channels = int(planes*(1-ratio))
        if t_channels != 0:
            self.km = KernelMask(t_channels, temperature=temperature)
            self.conv1_t = nn.Conv3d(inplanes, t_channels, 
                               kernel_size=(3, 1, 1), 
                               stride=(t_stride, 1, 1),
                               padding=(1, 0, 0), 
                               bias=False)
        if p_channels != 0:
            self.conv1_p = nn.Conv3d(inplanes, p_channels, 
                               kernel_size=(1, 1, 1), 
                               stride=(t_stride, 1, 1),
                               padding=(0, 0, 0), 
                               bias=False)

        self.bn1 = nn.BatchNorm3d(planes)
        self.conv2 = nn.Conv3d(planes, planes, 
                               kernel_size=(1, 3, 3), 
                               stride=(1, stride, stride), 
                               padding=(0, 1, 1), 
                               bias=False)
        self.bn2 = nn.BatchNorm3d(planes)
        self.conv3 = nn.Conv3d(planes, planes * self.expansion, 
                               kernel_size=1, 
                               bias=False)
        self.bn3 = nn.BatchNorm3d(planes * self.expansion)
        self.relu = nn.ReLU(inplace=True)
        self.downsample = downsample
        self.stride = stride
        self.t_stride = t_stride

    def forward(self, x):
        residual = x

        if self.ratio != 0:
            km = self.km()
            if km.device == torch.device(0):
                # pass
                print("output", km[0].view(-1))
                # print("mask", self.km.mask[0].view(-1))
            out_t = F.conv3d(x, km * self.conv1_t.weight, self.conv1_t.bias, (self.t_stride,1,1),
                        (1, 0, 0), (1, 1, 1), 1)
        if self.ratio != 1:
            out_p = self.conv1_p(x)
        
        if self.ratio == 0:
            out = out_p
        elif self.ratio == 1:
            out = out_t
        else:
            out = torch.cat((out_t, out_p), dim=1)

        out = self.bn1(out)
        out = self.relu(out)

        out = self.conv2(out)
        out = self.bn2(out)
        out = self.relu(out)

        out = self.conv3(out)
        out = self.bn3(out)

        if self.downsample is not None:
            residual = self.downsample(x)

        out += residual
        out = self.relu(out)

        return out

class KMBottleneck3D_v2(nn.Module):
    expansion = 4

    def __init__(self, inplanes, planes, 
                temperature=1, ratio=0.5, 
                stride=1, t_stride=1, downsample=None):
        super(KMBottleneck3D_v2, self).__init__()
        assert(ratio<=1 and ratio>=0), "Value of ratio must between 0 and 1."
        self.ratio = ratio
        t_channels = int(planes*ratio)
        p_channels = int(planes*(1-ratio))
        if t_channels != 0:
            self.km = KernelMask(t_channels, temperature=temperature)
            self.conv1_t = nn.Conv3d(inplanes, t_channels, 
                               kernel_size=(1, 1, 1), 
                               stride=(t_stride, 1, 1),
                               padding=(0, 0, 0), 
                               bias=False)
        if p_channels != 0:
            self.conv1_p = nn.Conv3d(inplanes, p_channels, 
                               kernel_size=(1, 1, 1), 
                               stride=(t_stride, 1, 1),
                               padding=(0, 0, 0), 
                               bias=False)

        self.bn1 = nn.BatchNorm3d(planes)
        self.conv2 = nn.Conv3d(planes, planes, 
                               kernel_size=(1, 3, 3), 
                               stride=(1, stride, stride), 
                               padding=(0, 1, 1), 
                               bias=False)
        self.bn2 = nn.BatchNorm3d(planes)
        self.conv3 = nn.Conv3d(planes, planes * self.expansion, 
                               kernel_size=1, 
                               bias=False)
        self.bn3 = nn.BatchNorm3d(planes * self.expansion)
        self.relu = nn.ReLU(inplace=True)
        self.downsample = downsample
        self.stride = stride
        self.t_stride = t_stride

    def forward(self, x):
        residual = x

        if self.ratio != 0:
            km = self.km()
            if km.device == torch.device(0):
                # pass
                print("output", km[0].view(-1))
                # print("mask", self.km.mask[0].view(-1))
            weight = torch.cat([self.conv1_t.weight,]*3, dim=2) / 3
            out_t = F.conv3d(x, km * weight, self.conv1_t.bias, (self.t_stride,1,1),
                        (1, 0, 0), (1, 1, 1), 1)
        if self.ratio != 1:
            out_p = self.conv1_p(x)
        
        if self.ratio == 0:
            out = out_p
        elif self.ratio == 1:
            out = out_t
        else:
            out = torch.cat((out_t, out_p), dim=1)

        out = self.bn1(out)
        out = self.relu(out)

        out = self.conv2(out)
        out = self.bn2(out)
        out = self.relu(out)

        out = self.conv3(out)
        out = self.bn3(out)

        if self.downsample is not None:
            residual = self.downsample(x)

        out += residual
        out = self.relu(out)

        return out

class PIBResNet3D_8fr(nn.Module):

    def __init__(self, block, layers, ratios, temperature=1, num_classes=1000, feat=False, **kwargs):
        if not isinstance(block, list):
            block = [block] * 4
        else:
            assert(len(block)) == 4, "Block number must be 4 for ResNet-Stype networks."
        self.inplanes = 64
        super(PIBResNet3D_8fr, self).__init__()
        self.feat = feat
        self.conv1 = nn.Conv3d(3, 64, 
                               kernel_size=(1, 7, 7), 
                               stride=(1, 2, 2), 
                               padding=(0, 3, 3),
                               bias=False)
        self.bn1 = nn.BatchNorm3d(64)
        self.relu = nn.ReLU(inplace=True)
        self.maxpool = nn.MaxPool3d(kernel_size=(1, 3, 3), 
                                    stride=(1, 2, 2), 
                                    padding=(0, 1, 1))
        self.layer1 = self._make_layer(block[0], 64, layers[0], inf_ratio=ratios[0], temperature=temperature)
        self.layer2 = self._make_layer(block[1], 128, layers[1], inf_ratio=ratios[1], temperature=temperature, stride=2)
        self.layer3 = self._make_layer(block[2], 256, layers[2], inf_ratio=ratios[2], temperature=temperature, stride=2, t_stride=2)
        self.layer4 = self._make_layer(block[3], 512, layers[3], inf_ratio=ratios[3], temperature=temperature, stride=2, t_stride=2)
        self.avgpool = GloAvgPool3d()
        self.feat_dim = 512 * block[0].expansion
        if not feat:
            self.fc = nn.Linear(512 * block[0].expansion, num_classes)

        for n, m in self.named_modules():
            if isinstance(m, nn.Conv3d):
                nn.init.kaiming_normal_(m.weight, mode='fan_out', nonlinearity='relu')
            elif isinstance(m, nn.BatchNorm3d) and "conv_t" not in n:
                nn.init.constant_(m.weight, 1)
                nn.init.constant_(m.bias, 0)


    def _make_layer(self, block, planes, blocks, inf_ratio, temperature=1, stride=1, t_stride=1):
        downsample = None
        if stride != 1 or self.inplanes != planes * block.expansion:
            downsample = nn.Sequential(
                nn.Conv3d(self.inplanes, planes * block.expansion,
                          kernel_size=1, stride=(t_stride, stride, stride), bias=False),
                nn.BatchNorm3d(planes * block.expansion),
            )

        layers = []
        layers.append(block(self.inplanes, planes, temperature=temperature, ratio=inf_ratio, stride=stride, t_stride=t_stride, downsample=downsample))
        self.inplanes = planes * block.expansion
        for i in range(1, blocks):
            layers.append(block(self.inplanes, planes, temperature=temperature, ratio=inf_ratio))

        return nn.Sequential(*layers)

    def forward(self, x):
        if x.device == torch.device(0):
            print("------------------------------------")
        x = self.conv1(x)
        x = self.bn1(x)
        x = self.relu(x)
        x = self.maxpool(x)

        x = self.layer1(x)
        x = self.layer2(x)
        x = self.layer3(x)
        x = self.layer4(x)


        x = self.avgpool(x)
        x = x.view(x.size(0), -1)
        if not self.feat:
            x = self.fc(x)

        return x


def part_state_dict(state_dict, model_dict, ratios):
    assert(len(ratios) == 4), "Length of ratios must equal to stage number"
    added_dict = {}
    for k, v in state_dict.items():
        # import pdb
        # pdb.set_trace()
        if ".conv1.weight" in k and "layer" in k:
                # import pdb
                # pdb.set_trace()
                ratio = ratios[int(k[k.index("layer")+5])-1]
                out_channels = v.shape[0]
                slice_index = int(out_channels*ratio)
                if ratio == 1:
                    new_k = k[:k.index(".conv1.weight")]+'.conv1_t.weight'
                    added_dict.update({new_k: v[:slice_index,...]})
                elif ratio == 0:
                    new_k = k[:k.index(".conv1.weight")]+'.conv1_p.weight'
                    added_dict.update({new_k: v[slice_index:,...]})
                else:
                    new_k = k[:k.index(".conv1.weight")]+'.conv1_t.weight'
                    added_dict.update({new_k: v[:slice_index,...]})
                    new_k = k[:k.index(".conv1.weight")]+'.conv1_p.weight'
                    added_dict.update({new_k: v[slice_index:,...]})

    state_dict.update(added_dict)
    pretrained_dict = {k: v for k, v in state_dict.items() if k in model_dict}
    pretrained_dict = inflate_state_dict(pretrained_dict, model_dict)
    model_dict.update(pretrained_dict)
    return model_dict


def inflate_state_dict(pretrained_dict, model_dict):
    for k in pretrained_dict.keys():
        if pretrained_dict[k].size() != model_dict[k].size():
            assert(pretrained_dict[k].size()[:2] == model_dict[k].size()[:2]), \
                   "To inflate, channel number should match."
            assert(pretrained_dict[k].size()[-2:] == model_dict[k].size()[-2:]), \
                   "To inflate, spatial kernel size should match."
            print("Layer {} needs inflation.".format(k))
            shape = list(pretrained_dict[k].shape)
            shape.insert(2, 1)
            t_length = model_dict[k].shape[2]
            pretrained_dict[k] = pretrained_dict[k].reshape(shape)
            if t_length != 1:
                pretrained_dict[k] = pretrained_dict[k].expand_as(model_dict[k]) / t_length
            assert(pretrained_dict[k].size() == model_dict[k].size()), \
                   "After inflation, model shape should match."

    return pretrained_dict

def km_resnet50_3d_v2_0init_tem_reciprocal16(pretrained=False, feat=False, **kwargs):
    """Constructs a ResNet-50 model.
    Args:
        pretrained (bool): If True, returns a model pre-trained on ImageNet
    """
    ratios = (1/2, 1/2, 1/2, 1/2)
    model = PIBResNet3D_8fr([KMBottleneck3D_v2, KMBottleneck3D_v2, KMBottleneck3D_v2, KMBottleneck3D_v2], 
                     [3, 4, 6, 3], ratios, temperature=1/16, feat=feat, **kwargs)
    if pretrained:
        if kwargs['pretrained_model'] is None:
            state_dict = model_zoo.load_url(model_urls['resnet50'])
        else:
            print("Using specified pretrain model")
            state_dict = kwargs['pretrained_model']
        if feat:
            new_state_dict = part_state_dict(state_dict, model.state_dict(), ratios)
            model.load_state_dict(new_state_dict)
    return model